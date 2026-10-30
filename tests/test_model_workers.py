"""Model workers retain retries and isolate concurrent attempts on one instance."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.workers.classification import worker as classification
from app.workers.collection import worker as collection
from app.workers.sql_retries import persist_with_retry
from psycopg.errors import DiskFull, QueryCanceled

from collector.budget import active_collection_budget
from collector.classification.repository import RepositoryClassification
from collector.diagnostics import Diagnostic, PipelineFailure
from collector.storage.models import CollectionResult

pytestmark = pytest.mark.anyio
VERSION = datetime(2026, 10, 30, tzinfo=timezone.utc)
COMPLETION_NAMES = {
    "classification": "complete_candidate_classification",
    "collection": "complete_collection_job",
}
FAILURE_NAMES = {
    "classification": "fail_candidate_classification",
    "collection": "mark_collection_job_error",
}


def attempt(kind, number=1):
    return {
        "id": uuid4() if kind == "classification" else number,
        "owner_id": f"owner-{number}",
        "updated_at": (VERSION + timedelta(seconds=number)).isoformat(),
        "kind": "source",
        "source_url": f"https://example.org/{number}",
    }


def make_worker(kind, compute):
    persist = partial(persist_with_retry, initial_delay=0)
    if kind == "classification":
        return classification.ClassificationWorker(
            classify=compute,
            vote_store_factory=Mock(),
            persist=persist,
        )
    return collection.CollectionWorker(
        classifier_factory=Mock(),
        vote_store_factory=Mock(),
        collect_source=compute,
        persist=persist,
    )


@pytest.mark.parametrize("kind", ["classification", "collection"])
@pytest.mark.parametrize("storage_failure", [DiskFull, QueryCanceled])
async def test_retry_schedule_survives_storage_failure_without_repeating_model(
    monkeypatch,
    kind,
    storage_failure,
):
    module = classification if kind == "classification" else collection
    diagnostic = Diagnostic(
        "llm_timeout",
        "classification",
        voter_id="model-a",
        attempt=1,
        retry_at="2026-11-01T00:00:00+00:00",
    )
    model_failure = PipelineFailure("Model timed out.", diagnostics=[diagnostic])
    compute = Mock(side_effect=model_failure)
    worker, job = make_worker(kind, compute), attempt(kind)
    calls = []

    async def schedule(item_id, version, diagnostics, *, collection):
        calls.append((item_id, version, diagnostics, collection))
        if len(calls) == 1:
            raise storage_failure("Scheduling storage is temporarily unavailable.")
        return True, diagnostics

    terminal = AsyncMock()
    completion = AsyncMock()
    monkeypatch.setattr(module, "schedule_llm_retry", schedule)
    monkeypatch.setattr(module, FAILURE_NAMES[kind], terminal)
    monkeypatch.setattr(module, COMPLETION_NAMES[kind], completion)

    with ThreadPoolExecutor(1) as executor:
        await asyncio.wait_for(worker.execute(job, executor), 1)

    compute.assert_called_once()
    completion.assert_not_awaited()
    terminal.assert_not_awaited()
    assert len(calls) == 2
    for item_id, version, diagnostics, is_collection in calls:
        assert item_id == job["id"]
        assert version == datetime.fromisoformat(job["updated_at"])
        assert diagnostics is model_failure.diagnostics
        assert diagnostics == [diagnostic]
        assert is_collection == (kind == "collection")


@pytest.mark.parametrize("kind", ["classification", "collection"])
async def test_refused_retry_keeps_enriched_diagnostics_and_original_attempt(
    monkeypatch,
    kind,
):
    module = classification if kind == "classification" else collection
    original = Diagnostic("llm_timeout", "classification", voter_id="model-a", attempt=3)
    enriched = [replace(original, max_attempts=3)]
    if kind == "collection":
        enriched.append(Diagnostic("collection_budget_exhausted", "collection"))
    failure = PipelineFailure("Model timed out.", diagnostics=[original])
    worker, job = make_worker(kind, Mock(side_effect=failure)), attempt(kind)
    schedule = AsyncMock(return_value=(False, enriched))
    terminal = AsyncMock()
    monkeypatch.setattr(module, "schedule_llm_retry", schedule)
    monkeypatch.setattr(module, FAILURE_NAMES[kind], terminal)

    with ThreadPoolExecutor(1) as executor:
        await worker.execute(job, executor)

    schedule.assert_awaited_once()
    terminal.assert_awaited_once()
    assert terminal.await_args.args == (
        (job["id"], job["owner_id"], str(failure))
        if kind == "classification"
        else (job["id"], str(failure))
    )
    assert terminal.await_args.kwargs == {
        "errors": [item.to_dict() for item in enriched],
        "expected_updated_at": datetime.fromisoformat(job["updated_at"]),
    }


@pytest.mark.parametrize("kind", ["classification", "collection"])
async def test_shared_worker_keeps_concurrent_results_and_versions_separate(monkeypatch, kind):
    module = classification if kind == "classification" else collection
    jobs = [attempt(kind, number) for number in (1, 2)]
    expected_results = {
        job["id"]: (
            RepositoryClassification("relevant", reason=job["owner_id"])
            if kind == "classification"
            else CollectionResult()
        )
        for job in jobs
    }
    entered, release = asyncio.Event(), asyncio.Event()
    completed = []

    def compute(item, *_args, **_kwargs):
        item_id = (
            item["id"]
            if kind == "classification"
            else next(job["id"] for job in jobs if job["source_url"] == item)
        )
        return expected_results[item_id]

    async def complete(item_id, *args, expected_updated_at):
        owner_id, result = args if kind == "classification" else (None, args[0])
        completed.append((item_id, owner_id, result, expected_updated_at))
        if len(completed) == 2:
            entered.set()
        await release.wait()

    worker = make_worker(kind, compute)
    terminal = AsyncMock()
    monkeypatch.setattr(module, COMPLETION_NAMES[kind], complete)
    monkeypatch.setattr(module, FAILURE_NAMES[kind], terminal)

    with ThreadPoolExecutor(2) as executor:
        tasks = [asyncio.create_task(worker.execute(job, executor)) for job in jobs]
        try:
            await asyncio.wait_for(entered.wait(), 1)
        finally:
            release.set()
            await asyncio.gather(*tasks)

    assert len(completed) == 2
    for job in jobs:
        saved = next(entry for entry in completed if entry[0] == job["id"])
        assert saved[1] == (job["owner_id"] if kind == "classification" else None)
        assert saved[2] is expected_results[job["id"]]
        assert saved[3] == datetime.fromisoformat(job["updated_at"])
    terminal.assert_not_awaited()
    assert all("_vote_store" not in job for job in jobs)


@pytest.mark.parametrize("kind", ["source", "repository_candidate"])
async def test_collection_budget_covers_compute_and_not_persistence(monkeypatch, kind):
    job = {**attempt("collection"), "kind": kind}
    budgets = []
    result = CollectionResult()

    def compute(url, **kwargs):
        budgets.append(active_collection_budget())
        return result

    async def complete(*args, **kwargs):
        assert active_collection_budget() is None

    source, record = Mock(side_effect=compute), Mock(side_effect=compute)
    trace_factory = Mock()
    worker = collection.CollectionWorker(
        classifier_factory=Mock(),
        vote_store_factory=Mock(),
        trace_factory=trace_factory,
        collect_source=source,
        collect_record=record,
    )
    completion = AsyncMock(side_effect=complete)
    monkeypatch.setattr(collection, "complete_collection_job", completion)
    with ThreadPoolExecutor(1) as executor:
        await worker.execute(job, executor)

    assert len(budgets) == 1 and budgets[0] is not None
    completion.assert_awaited_once_with(
        job["id"],
        result,
        expected_updated_at=datetime.fromisoformat(job["updated_at"]),
    )
    if kind == "repository_candidate":
        record.assert_called_once()
        source.assert_not_called()
        trace_factory.assert_called_once()
        assert record.call_args.kwargs["observe"] is trace_factory.return_value
    else:
        source.assert_called_once()
        record.assert_not_called()
        trace_factory.assert_not_called()
