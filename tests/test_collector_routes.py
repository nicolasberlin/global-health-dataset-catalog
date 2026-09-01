from __future__ import annotations

import asyncio
import threading
import time

import pytest
from app.routes.collector import (
    _run_collection_job,
    classify_repository_result,
    list_collected,
    read_collection_job,
    search_repositories,
    start_collection_job,
)
from app.routes.collector_schemas import (
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
    CollectorURLRequest,
)
from fastapi import BackgroundTasks, HTTPException

from collector.classification.page import PageClassificationError
from collector.classification.repository import RepositoryClassification
from collector.config import DEFAULT_CONFIG
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
)
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
)

pytestmark = pytest.mark.anyio


def _use_accepting_repository_classifier(monkeypatch):
    class AcceptingRepositoryClassifier:
        def classify(self, page):
            return RepositoryClassification(
                relevance_label="relevant",
                reason=f"{page.title} matches the search query.",
                ensemble=_accepted_repository_ensemble(
                    reason=f"{page.title} matches the search query."
                ),
            )

    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda config=DEFAULT_CONFIG: AcceptingRepositoryClassifier(),
    )


def _accepted_repository_ensemble(*, reason: str) -> dict[str, object]:
    voters = [
        {
            "voter_id": voter_id,
            "accepted": True,
            "relevance_label": "relevant",
            "reason": reason,
            "missing_information": [],
        }
        for voter_id in ("llm_a", "llm_b", "llm_c")
    ]
    return {
        "votes_required": 2,
        "minimum_successful_votes": 2,
        "successful_votes": 3,
        "failed_votes": 0,
        "accepted_votes": 3,
        "decision": "accepted",
        "decision_reason": "enough_accept_votes",
        "decision_voter_ids": ["llm_a", "llm_b", "llm_c"],
        "voters": voters,
        "failures": [],
    }


async def test_collector_search_repositories_route_accepts_query_and_returns_results(
    monkeypatch,
):
    def fake_search_repository_metadata(query):
        assert query == "malaria mortality"
        return RepositorySearchResponse(
            results=[
                RepositorySearchResult(
                    title="Malaria mortality estimates",
                    description="Annual mortality estimates by country.",
                    url="https://example.org/datasets/malaria-mortality",
                    source="DataCite",
                    publisher="Global Health Repository",
                    date="2025",
                    doi="10.1234/example",
                    keywords=["malaria", "mortality"],
                    metadata={
                        "Title": "Malaria mortality estimates",
                        "Geography": "France",
                        "Date of publication": "2025",
                        "Dataset URL": "https://example.org/datasets/malaria-mortality",
                        "Disease(s)": "malaria",
                        "Size of dataset": "NA",
                        "Demographic information": "NA",
                        "Sharing license": "CC-BY-4.0",
                        "Modality of data": "tabular",
                        "Description of dataset": "Annual mortality estimates by country.",
                    },
                )
            ],
            warnings=[
                RepositorySearchWarning(
                    provider="HDX",
                    message="This source could not be searched.",
                )
            ],
        )

    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fake_search_repository_metadata,
    )

    response = await search_repositories(
        CollectorRepositorySearchRequest(query=" malaria mortality ")
    )

    assert response.query == "malaria mortality"
    assert len(response.items) == 1
    item = response.items[0]
    assert item.title == "Malaria mortality estimates"
    assert item.source == "DataCite"
    assert item.search_query == "malaria mortality"
    assert item.publisher == "Global Health Repository"
    assert item.date == "2025"
    assert item.doi == "10.1234/example"
    assert item.keywords == ["malaria", "mortality"]
    assert item.classification is None
    assert len(response.warnings) == 1
    assert response.warnings[0].provider == "HDX"
    assert response.warnings[0].message == "This source could not be searched."


async def test_collector_classify_repository_result_route_returns_classification(
    monkeypatch,
):
    _use_accepting_repository_classifier(monkeypatch)

    response = await classify_repository_result(
        CollectorRepositorySearchItem(
            title="Malaria mortality estimates",
            description="Annual mortality estimates by country.",
            url="https://example.org/datasets/malaria-mortality",
            source="DataCite",
            search_query="malaria mortality",
            publisher="Global Health Repository",
            date="2025",
            doi="10.1234/example",
            keywords=["malaria", "mortality"],
            metadata={
                "Title": "Malaria mortality estimates",
                "Geography": "France",
                "Date of publication": "2025",
                "Dataset URL": "https://example.org/datasets/malaria-mortality",
                "Disease(s)": "malaria",
                "Size of dataset": "NA",
                "Demographic information": "NA",
                "Sharing license": "CC-BY-4.0",
                "Modality of data": "tabular",
                "Description of dataset": "Annual mortality estimates by country.",
            },
        )
    )

    assert response.title == "Malaria mortality estimates"
    assert response.classification is not None
    assert response.classification.accepted is True
    assert response.classification.relevance_label == "relevant"
    assert response.classification.reason == (
        "Malaria mortality estimates matches the search query."
    )


async def test_collector_classify_repository_result_route_returns_502_when_classification_fails(
    monkeypatch,
    caplog,
):
    class FailingClassifier:
        def classify(self, page):
            raise PageClassificationError("LLM classification failed.")

    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda config=DEFAULT_CONFIG: FailingClassifier(),
    )
    caplog.set_level("ERROR", logger="app.routes.collector")

    try:
        await classify_repository_result(
            CollectorRepositorySearchItem(
                title="Malaria mortality estimates",
                url="https://example.org/datasets/malaria-mortality",
                source="DataCite",
                search_query="malaria mortality",
            )
        )
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Page classification failed."
        assert "DataCite" in caplog.text
        assert "https://example.org/datasets/malaria-mortality" in caplog.text
        assert "LLM classification failed." in caplog.text
    else:
        raise AssertionError("Expected HTTPException.")


async def test_collector_repository_classification_limits_backend_concurrency(
    monkeypatch,
):
    active_calls = 0
    maximum_active_calls = 0
    counter_lock = threading.Lock()
    worker_pair = threading.Barrier(2)

    def fake_classify_one_repository_result(result, classifier):
        nonlocal active_calls, maximum_active_calls
        with counter_lock:
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)

        worker_pair.wait(timeout=1)
        time.sleep(0.02)

        with counter_lock:
            active_calls -= 1
        return result

    monkeypatch.setattr(
        "app.routes.collector.classify_one_repository_result",
        fake_classify_one_repository_result,
    )
    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda config=DEFAULT_CONFIG: object(),
    )
    payload = CollectorRepositorySearchItem(
        title="Malaria mortality estimates",
        url="https://example.org/datasets/malaria-mortality",
        source="DataCite",
        search_query="malaria mortality",
    )

    await asyncio.gather(
        *(classify_repository_result(payload) for _request in range(4))
    )

    assert maximum_active_calls == 2


async def test_collector_classify_repository_result_route_requires_search_query():
    try:
        await classify_repository_result(
            CollectorRepositorySearchItem(
                title="Malaria mortality estimates",
                url="https://example.org/datasets/malaria-mortality",
                source="DataCite",
            )
        )
    except HTTPException as exception:
        assert exception.status_code == 400
        assert exception.detail == "Search query is required"
    else:
        raise AssertionError("Expected HTTPException.")


async def test_collector_search_repositories_route_returns_bad_gateway_for_provider_errors(
    monkeypatch,
):
    def fake_search_repository_metadata(query):
        raise ValueError("Could not fetch JSON URL: timeout")

    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fake_search_repository_metadata,
    )

    try:
        await search_repositories(
            CollectorRepositorySearchRequest(query="malaria mortality")
        )
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Repository search failed."
    else:
        raise AssertionError("Expected HTTPException.")


def test_collector_search_repositories_request_rejects_too_long_query():
    try:
        CollectorRepositorySearchRequest(query="x" * 301)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected validation error.")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("title", "x" * 501),
        ("description", "x" * 20_001),
        ("keywords", ["x" * 201]),
        ("metadata", {"blob": "x" * 100_001}),
    ],
)
def test_collector_repository_item_rejects_oversized_llm_input(
    field_name,
    value,
):
    item_data = {
        "title": "Malaria mortality estimates",
        "url": "https://example.org/datasets/malaria-mortality",
        "source": "DataCite",
        field_name: value,
    }

    with pytest.raises(ValueError):
        CollectorRepositorySearchItem(**item_data)


def test_collector_repository_item_rejects_incomplete_classification_contract():
    with pytest.raises(ValueError):
        CollectorRepositorySearchItem(
            title="Malaria mortality estimates",
            url="https://example.org/datasets/malaria-mortality",
            source="DataCite",
            classification={"accepted": True},
        )


async def test_collector_start_collection_job_route_enqueues_background_task(monkeypatch):
    async def fake_create_collection_job(source_url):
        assert source_url == "https://catalog.example.org/"
        return {
            "id": 12,
            "source_url": source_url,
            "status": "pending",
            "saved_count": 0,
            "message": "Collecte en attente.",
            "error": "",
            "created_at": "2026-08-16 12:00:00",
            "updated_at": "2026-08-16 12:00:00",
            "finished_at": "",
        }

    background_tasks = BackgroundTasks()

    monkeypatch.setattr(
        "app.routes.collector.db_create_collection_job",
        fake_create_collection_job,
    )

    response = await start_collection_job(
        CollectorURLRequest(url="https://catalog.example.org"),
        background_tasks,
    )

    assert response.job.id == 12
    assert response.job.status == "pending"
    assert len(background_tasks.tasks) == 1


async def test_collector_read_collection_job_route_returns_status(monkeypatch):
    async def fake_get_collection_job(job_id):
        assert job_id == 12
        return {
            "id": 12,
            "source_url": "https://catalog.example.org/",
            "status": "done",
            "saved_count": 2,
            "discovered_count": 10,
            "analyzed_count": 5,
            "accepted_count": 2,
            "rejected_count": 3,
            "invalid_distribution_count": 1,
            "discovery_methods": ["sitemap"],
            "message": "2 dataset(s) sauvegardé(s).",
            "error": "",
            "created_at": "2026-08-16 12:00:00",
            "updated_at": "2026-08-16 12:01:00",
            "finished_at": "2026-08-16 12:01:00",
        }

    monkeypatch.setattr("app.routes.collector.get_collection_job", fake_get_collection_job)

    response = await read_collection_job(12)

    assert response.job.id == 12
    assert response.job.status == "done"
    assert response.job.saved_count == 2
    assert response.job.discovered_count == 10
    assert response.job.discovery_methods == ["sitemap"]


async def test_collector_read_collection_job_route_returns_not_found(monkeypatch):
    async def fake_get_collection_job(job_id):
        return None

    monkeypatch.setattr("app.routes.collector.get_collection_job", fake_get_collection_job)

    try:
        await read_collection_job(404)
    except HTTPException as exception:
        assert exception.status_code == 404
        assert exception.detail == "Collection job not found"
    else:
        raise AssertionError("Expected HTTPException.")


async def test_run_collection_job_marks_done(monkeypatch):
    calls = []

    def fake_collect_source_with_report(source_url):
        calls.append(("collect", source_url))
        return CollectionResult(
            datasets=[
                CollectedDataset(
                    dataset_url="https://catalog.example.org/dataset/mortality",
                    title="Mortality health dataset",
                    description="Official mortality health data.",
                    publisher="National Health Agency",
                    hosting_platform="",
                    uploader="",
                    dataset_signals={},
                    health_signals={},
                    distributions=[],
                    discovery_method="ckan",
                    validation_results=[],
                )
            ],
            report=CollectionReport(
                discovered_count=5,
                analyzed_count=5,
                accepted_count=1,
                rejected_count=4,
                invalid_distribution_count=1,
                discovery_methods=("ckan",),
            ),
        )

    async def fake_save_collected_datasets(source_url, datasets, collection_job_id=None):
        calls.append(("save", source_url, len(datasets), collection_job_id))
        return datasets

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return {"id": job_id, "status": "running"}

    async def fake_mark_collection_job_done(job_id, saved_count, report):
        calls.append(
            ("done", job_id, saved_count, report.discovered_count, report.discovery_methods)
        )

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.save_collected_datasets",
        fake_save_collected_datasets,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_done",
        fake_mark_collection_job_done,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [
        ("running", 12),
        ("collect", "https://catalog.example.org/"),
        ("save", "https://catalog.example.org/", 1, 12),
        ("done", 12, 1, 5, ("ckan",)),
    ]


async def test_run_collection_job_stops_when_job_cannot_be_started(monkeypatch):
    calls = []

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return None

    def fake_collect_source_with_report(source_url):
        calls.append(("collect", source_url))
        raise AssertionError("Collection should not run for a stale job.")

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [("running", 12)]


async def test_run_collection_job_marks_errors(monkeypatch):
    calls = []

    def fake_collect_source_with_report(source_url):
        raise ValueError("bad source")

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return {"id": job_id, "status": "running"}

    async def fake_mark_collection_job_error(job_id, error):
        calls.append(("error", job_id, error))

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_error",
        fake_mark_collection_job_error,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [("running", 12), ("error", 12, "bad source")]


async def test_collector_list_collected_route_returns_saved_datasets(monkeypatch):
    async def fake_list_collected_datasets():
        return [
            CollectedDataset(
                dataset_url="https://catalog.example.org/dataset/mortality",
                title="Mortality health dataset",
                description="Official mortality health data.",
                publisher="National Health Agency",
                hosting_platform="",
                uploader="",
                geography=("France",),
                dataset_signals={},
                health_signals={},
                distributions=[],
                discovery_method="ckan",
                validation_results=[],
                source_url="https://catalog.example.org/",
                database_id=7,
                updated_at="2026-08-16 12:00:00",
            )
        ]

    monkeypatch.setattr(
        "app.routes.collector.list_collected_datasets",
        fake_list_collected_datasets,
    )

    response = await list_collected()

    assert len(response.items) == 1
    assert response.items[0].id == 7
    assert response.items[0].source_url == "https://catalog.example.org/"
    assert response.items[0].geography == ["France"]
    assert response.items[0].updated_at == "2026-08-16 12:00:00"
