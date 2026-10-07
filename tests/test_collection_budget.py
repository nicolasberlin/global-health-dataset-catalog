"""Collection deadlines preserve proven results and never become negative votes."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest
from app import collection_worker
from app.db.connection import _require_database_pool
from app.routes.collector import search_progress
from app.security import APIPrincipal
from fastapi import Response
from test_collection_workflow import candidate_for, decision, wait_until
from test_collector_pipeline import DATASET_HTML, AcceptingPageClassifier

from collector.budget import (
    CollectionBudgetExceeded,
    active_collection_budget,
    check_collection_budget,
    collection_budget,
)
from collector.classification.voting import run_voters
from collector.config import CollectorConfig, configured_collection_budget_seconds
from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage
from collector.main import collect_repository_candidate_with_report, collect_source_with_report
from collector.storage.models import DistributionCandidate, ValidationResult


@pytest.fixture
def clock(monkeypatch):
    values = [100.0]
    monkeypatch.setattr("collector.budget.monotonic", lambda: values[0])
    return values


def page(name="one", links=1):
    return DiscoveredPage(
        url=f"https://example.org/datasets/{name}",
        title="Health data",
        discovery_method="test",
        distributions=tuple(
            DistributionCandidate(
                f"https://example.org/files/{name}-{index}.csv",
                "CSV",
                0.9,
            )
            for index in range(links)
        ),
    )


def available(distribution):
    return ValidationResult(distribution.url, distribution.url, "CSV", True, 200)


def collect(pages, *, validate=available, classifier=None, config=None):
    return collect_source_with_report(
        "https://example.org",
        discover=lambda _: pages,
        validate=validate,
        classifier=classifier or AcceptingPageClassifier(),
        config=config or CollectorConfig(collection_max_duration_seconds=5),
    )


def assert_expired(result):
    assert not result.report.verification_complete
    assert any(error.code == "collection_budget_exhausted" for error in result.report.errors)


@pytest.mark.parametrize("value", ["0", "-1", "3601", "nan", "inf", "bad"])
def test_budget_configuration_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", value)
    with pytest.raises(ValueError):
        configured_collection_budget_seconds()


def test_budget_configuration_supports_fractional_seconds(monkeypatch):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "12.5")
    assert configured_collection_budget_seconds() == 12.5
    assert (
        CollectorConfig(collection_max_duration_seconds=12.5).collection_max_duration_seconds
        == 12.5
    )
    with pytest.raises(ValueError):
        CollectorConfig(collection_max_duration_seconds=float("nan"))


def test_nested_collection_inherits_deadline_and_context_is_cleared(clock):
    with collection_budget(seconds=5) as original:
        with collection_budget(seconds=1000) as nested:
            assert original is nested
            clock[0] += 5
            with pytest.raises(CollectionBudgetExceeded):
                check_collection_budget()
    assert active_collection_budget() is None
    with collection_budget(seconds=5):
        check_collection_budget()


def test_expiry_during_discovery_is_incomplete_even_without_candidates(clock):
    def discover(_):
        clock[0] += 6
        return []

    result = collect_source_with_report(
        "https://example.org",
        discover=discover,
        classifier=AcceptingPageClassifier(),
        config=CollectorConfig(collection_max_duration_seconds=5),
    )
    assert_expired(result)
    assert result.report.analyzed_count == result.report.rejected_count == 0


def test_expiry_preserves_first_dataset_and_stops_before_second_page(clock):
    def validate(distribution):
        clock[0] += 5
        return available(distribution)

    result = collect([page("one"), page("two")], validate=validate)
    assert_expired(result)
    assert len(result.datasets) == 1
    assert result.datasets[0].dataset_url.endswith("one")
    assert result.report.discovered_count == 2 and result.report.analyzed_count == 1
    assert result.report.accepted_count == 1 and result.report.rejected_count == 0


def test_expiry_retains_valid_link_when_later_probe_is_interrupted(clock):
    calls = []

    def validate(distribution):
        calls.append(distribution.url)
        if len(calls) == 2:
            clock[0] += 5
            check_collection_budget()
        return available(distribution)

    result = collect(
        [page(links=3)],
        validate=validate,
        config=CollectorConfig(
            collection_max_duration_seconds=5,
            max_distributions_saved=3,
        ),
    )
    assert_expired(result)
    assert len(calls) == 2 and len(result.datasets) == 1
    assert len(result.datasets[0].distributions) == 1
    assert result.report.invalid_distribution_count == 0


def test_interrupted_page_preserves_previous_failed_validation_evidence(clock):
    calls = []

    def validate(distribution):
        calls.append(distribution.url)
        if len(calls) == 2:
            clock[0] += 5
            check_collection_budget()
        return replace(available(distribution), ok=False, status="unconfirmed")

    result = collect([page(links=3)], validate=validate)
    assert_expired(result)
    assert not result.datasets and result.report.rejected_count == 0
    assert result.report.invalid_distribution_count == len(result.report.validation_failures) == 1


def test_expired_fetch_does_not_start_classifier(clock):
    class NeverClassify:
        def classify(self, *_):
            pytest.fail("A classifier must not start after the fetch exhausted the budget")

    def fetch(url):
        clock[0] += 5
        return FetchedPage(url, url, DATASET_HTML, 200, "text/html")

    result = collect_repository_candidate_with_report(
        "https://example.org/datasets/one",
        fetch_html=fetch,
        classifier=NeverClassify(),
        config=CollectorConfig(collection_max_duration_seconds=5),
    )
    assert_expired(result)
    assert not result.datasets and result.report.rejected_count == 0


def test_each_voter_inherits_the_same_budget(clock):
    def classify(_):
        assert active_collection_budget() is budget
        check_collection_budget()

    with collection_budget(seconds=5) as budget:
        clock[0] += 5
        with pytest.raises(CollectionBudgetExceeded):
            run_voters(
                [("a", object()), ("b", object()), ("c", object())],
                classify=classify,
                make_vote=lambda *args: pytest.fail("No semantic vote"),
                handled_errors=(),
            )


@pytest.mark.anyio
async def test_worker_keeps_slot_and_persists_partial_result_after_expiration(
    database,
    monkeypatch,
    clock,
):
    await database.init_database()
    candidate = await candidate_for(database)
    await database.complete_search_session(candidate["search_session_id"], "alice", origin="online")
    result = await database.complete_candidate_classification(candidate["id"], "alice", decision())
    job_id = result.collection.job["id"]
    other = await database.create_collection_job("https://example.org/another")
    entered, release = threading.Event(), threading.Event()

    def validate(distribution):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
            clock[0] += 1000
        return available(distribution)

    def collect_owned(_url, *, classifier):
        return collect([page("one"), page("two")], validate=validate)

    monkeypatch.setattr(
        collection_worker, "collect_repository_candidate_with_report", collect_owned
    )
    # Stop a second job without making a provider call if the worker claims it after release.
    monkeypatch.setattr(collection_worker, "collect_source_with_report", collect_owned)
    async with collection_worker.collection_workers(concurrency=1, poll_interval=0.01):
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            assert (await database.get_collection_job(other["id"]))["status"] == "pending"
            assert (await database.get_collection_job(job_id))["status"] == "running"
        finally:
            release.set()

        async def completed():
            return (await database.get_collection_job(job_id))["status"] == "done"

        await wait_until(completed)
    job = await database.get_collection_job(job_id)
    assert job["saved_count"] == 1 and job["outcome"] == "incomplete"
    assert job["errors"][0]["code"] == "collection_budget_exhausted"
    progress = await search_progress(
        candidate["search_session_id"], APIPrincipal("alice"), Response()
    )
    assert not progress.polling_required and progress.outcome == "incomplete"
    assert len(progress.dataset_ids) == 1
    async with _require_database_pool().connection() as connection:
        cursor = await connection.execute(
            "SELECT retry_round FROM collection_jobs WHERE id = %s", (job_id,)
        )
        assert (await cursor.fetchone())["retry_round"] == 0


@pytest.mark.anyio
async def test_expired_job_concludes_without_any_external_call(database, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    await database.init_database()
    candidate = await candidate_for(database)
    await database.complete_candidate_classification(candidate["id"], "alice", decision())
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE collection_jobs SET collection_deadline_at = NOW() - INTERVAL '1 second'"
        )
    job = await database.claim_pending_collection_job()
    monkeypatch.setattr("collector.main.fetch_public_html", lambda *a, **kw: pytest.fail("fetch"))
    monkeypatch.setattr(
        "collector.classification.llm_client.HTTPJSONLLMClient._classify_request",
        lambda *a, **kw: pytest.fail("LLM"),
    )
    with ThreadPoolExecutor(1) as executor:
        await collection_worker._run_collection_job(job, executor)
    finished = await database.get_collection_job(job["id"])
    assert finished["status"] == "done" and finished["outcome"] == "incomplete"
    assert finished["errors"][0]["code"] == "collection_budget_exhausted"
    assert finished["analyzed_count"] == 0
