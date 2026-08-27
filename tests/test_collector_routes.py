from __future__ import annotations

import pytest
from app.routes.collector import (
    _analyze_html,
    _run_collection_job,
    analyze_html,
    analyze_url,
    collect_url,
    discover_url,
    list_collected,
    read_collection_job,
    search_repositories,
    start_collection_job,
)
from app.routes.collector_schemas import (
    CollectorAnalyzeHTMLRequest,
    CollectorCollectURLRequest,
    CollectorRepositorySearchRequest,
    CollectorURLRequest,
)
from fastapi import BackgroundTasks, HTTPException

from collector.classification.heuristic import HeuristicPageClassifier
from collector.classification.page import PageClassificationError
from collector.config import DEFAULT_CONFIG
from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
)
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    ValidationResult,
)

pytestmark = pytest.mark.anyio


def _use_heuristic_default_classifier(monkeypatch):
    monkeypatch.setattr(
        "app.routes.collector.build_default_page_classifier",
        lambda config=DEFAULT_CONFIG: HeuristicPageClassifier(config),
    )


async def test_collector_analyze_html_route_returns_scores_and_distributions(monkeypatch):
    _use_heuristic_default_classifier(monkeypatch)
    threaded_calls = []

    async def fake_to_thread(function, *args, **kwargs):
        threaded_calls.append((function, args))
        return function(*args, **kwargs)

    monkeypatch.setattr("app.routes.collector.asyncio.to_thread", fake_to_thread)
    payload = CollectorAnalyzeHTMLRequest(
        url="https://example.org/datasets/mortality",
        html="""
        <html>
            <head>
                <title>Mortality health dataset</title>
                <meta name="description" content="Official health mortality data." />
                <script type="application/ld+json">
                {
                    "@context": "https://schema.org",
                    "@type": "Dataset",
                    "publisher": {"name": "National Health Agency"},
                    "spatialCoverage": {"@type": "Country", "name": "France"},
                    "distribution": {
                        "@type": "DataDownload",
                        "contentUrl": "https://example.org/files/mortality.csv",
                        "encodingFormat": "text/csv"
                    }
                }
                </script>
            </head>
            <body>
                <h1>Mortality health dataset</h1>
                <p>Mortality and epidemiology indicators.</p>
                <a href="https://example.org/files/mortality.xlsx">Download XLSX</a>
            </body>
        </html>
        """,
    )

    response = await analyze_html(payload)

    assert response.accepted is True
    assert response.publisher == "National Health Agency"
    assert response.hosting_platform == ""
    assert response.uploader == ""
    assert response.geography == ["France"]
    assert response.dataset_probability >= 0.9
    assert response.health_probability >= 0.35
    assert response.health_label in {"HEALTH", "PARTIALLY_HEALTH"}
    assert {distribution.format for distribution in response.distributions} == {"CSV", "XLSX"}
    assert threaded_calls == [
        (
            _analyze_html,
            ("https://example.org/datasets/mortality", payload.html),
        )
    ]


async def test_collector_analyze_url_route_fetches_and_analyzes_html(monkeypatch):
    _use_heuristic_default_classifier(monkeypatch)
    threaded_calls = []

    async def fake_to_thread(function, *args, **kwargs):
        threaded_calls.append((function, args))
        return function(*args, **kwargs)

    def fake_fetch_public_html(url):
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            html="""
            <html>
                <head>
                    <title>Vaccination dataset</title>
                    <script type="application/ld+json">
                    {"@type": "Dataset"}
                    </script>
                </head>
                <body>
                    <h1>Vaccination health dataset</h1>
                    <p>Vaccination and epidemiology data.</p>
                    <a href="https://example.org/files/vaccination.csv">Download CSV</a>
                </body>
            </html>
            """,
        )

    monkeypatch.setattr("app.routes.collector.fetch_public_html", fake_fetch_public_html)
    monkeypatch.setattr("app.routes.collector.asyncio.to_thread", fake_to_thread)

    response = await analyze_url(CollectorURLRequest(url="https://example.org/catalog"))

    assert response.accepted is True
    assert response.publisher == ""
    assert response.hosting_platform == ""
    assert response.uploader == ""
    assert response.dataset_probability >= 0.6
    assert response.health_probability >= 0.35
    assert {distribution.format for distribution in response.distributions} == {"CSV"}
    assert [function for function, _args in threaded_calls] == [
        fake_fetch_public_html,
        _analyze_html,
    ]


def test_collector_analyze_html_route_returns_502_when_classification_fails():
    class FailingClassifier:
        def classify(self, page, distributions):
            raise PageClassificationError("LLM classification failed.")

    try:
        _analyze_html(
            "https://example.org/datasets/mortality",
            "<html><head><title>Mortality dataset</title></head></html>",
            classifier=FailingClassifier(),
        )
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Page classification failed."
    else:
        raise AssertionError("Expected HTTPException.")


def test_collector_analyze_html_route_uses_llm_default_classifier(monkeypatch):
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_1", "model-a")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_2", "model-b")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_3", "model-c")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        _analyze_html(
            "https://example.org/datasets/mortality",
            "<html><head><title>Mortality dataset</title></head></html>",
        )
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Page classification failed."
    else:
        raise AssertionError("Expected HTTPException.")


async def test_collector_discover_url_route_returns_discovered_pages(monkeypatch):
    def fake_discover_source(url):
        assert url == "https://catalog.example.org/"
        return [
            DiscoveredPage(
                url="https://catalog.example.org/dataset/mortality",
                discovery_method="ckan",
                priority=0.9,
                title="Mortality dataset",
                description="Official mortality health data.",
                publisher="National Health Agency",
                geography=("France",),
                discovery_metadata={"ckan_name": "mortality"},
                distributions=(
                    DistributionCandidate(
                        url="https://catalog.example.org/files/mortality.csv",
                        format="CSV",
                        probability=0.95,
                        anchor="CSV download",
                        mime_type="text/csv",
                    ),
                ),
            )
        ]

    monkeypatch.setattr("app.routes.collector.discover_source", fake_discover_source)

    response = await discover_url(CollectorURLRequest(url="https://catalog.example.org"))

    assert len(response.items) == 1
    item = response.items[0]
    assert item.url == "https://catalog.example.org/dataset/mortality"
    assert item.discovery_method == "ckan"
    assert item.priority == 0.9
    assert item.title == "Mortality dataset"
    assert item.description == "Official mortality health data."
    assert item.publisher == "National Health Agency"
    assert item.geography == ["France"]
    assert item.discovery_metadata == {"ckan_name": "mortality"}
    assert len(item.distributions) == 1
    assert item.distributions[0].url == "https://catalog.example.org/files/mortality.csv"
    assert item.distributions[0].format == "CSV"
    assert item.distributions[0].mime_type == "text/csv"


async def test_collector_discover_url_route_returns_bad_request_for_discovery_errors(
    monkeypatch,
):
    def fake_discover_source(url):
        raise ValueError(f"Could not discover {url}")

    monkeypatch.setattr("app.routes.collector.discover_source", fake_discover_source)

    try:
        await discover_url(CollectorURLRequest(url="https://catalog.example.org"))
    except HTTPException as exception:
        assert exception.status_code == 400
        assert exception.detail == "Could not discover https://catalog.example.org/"
    else:
        raise AssertionError("Expected HTTPException.")


async def test_collector_search_repositories_route_accepts_query_and_returns_results(
    monkeypatch,
):
    _use_heuristic_default_classifier(monkeypatch)

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
                    relevance_score=0.93,
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
    assert item.publisher == "Global Health Repository"
    assert item.date == "2025"
    assert item.doi == "10.1234/example"
    assert item.keywords == ["malaria", "mortality"]
    assert item.relevance_score == 0.93
    assert item.classification is not None
    assert item.classification["health_label"] in {"HEALTH", "PARTIALLY_HEALTH"}
    assert len(response.warnings) == 1
    assert response.warnings[0].provider == "HDX"
    assert response.warnings[0].message == "This source could not be searched."


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


async def test_collector_collect_url_route_returns_collected_datasets(monkeypatch):
    saved_calls = []

    def fake_collect_source(url):
        assert url == "https://catalog.example.org/"
        return [
            CollectedDataset(
                dataset_url="https://catalog.example.org/dataset/mortality",
                title="Mortality health dataset",
                description="Official mortality health data.",
                publisher="National Health Agency",
                hosting_platform="",
                uploader="",
                geography=("France",),
                dataset_probability=0.92,
                dataset_signals={"schema_dataset": True},
                health_probability=0.8,
                health_label="HEALTH",
                health_signals={"matched_keywords": ["mortality"]},
                distributions=[
                    DistributionCandidate(
                        url="https://catalog.example.org/files/mortality.csv",
                        format="CSV",
                        probability=0.95,
                        anchor="CSV download",
                        mime_type="text/csv",
                    )
                ],
                discovery_method="ckan",
                validation_results=[
                    ValidationResult(
                        url="https://catalog.example.org/files/mortality.csv",
                        final_url="https://catalog.example.org/files/mortality.csv",
                        format="CSV",
                        ok=True,
                        http_status=200,
                        mime_type="text/csv",
                        size_bytes=123,
                    )
                ],
            )
        ]

    async def fake_save_collected_datasets(source_url, datasets):
        saved_calls.append((source_url, datasets))
        return datasets

    monkeypatch.setattr("app.routes.collector.collect_source", fake_collect_source)
    monkeypatch.setattr(
        "app.routes.collector.save_collected_datasets",
        fake_save_collected_datasets,
    )

    response = await collect_url(
        CollectorCollectURLRequest(url="https://catalog.example.org")
    )

    assert len(saved_calls) == 1
    assert saved_calls[0][0] == "https://catalog.example.org/"
    assert len(response.items) == 1
    assert response.saved is True
    assert response.saved_count == 1
    item = response.items[0]
    assert item.dataset_url == "https://catalog.example.org/dataset/mortality"
    assert item.discovery_method == "ckan"
    assert item.geography == ["France"]
    assert item.dataset_probability == 0.92
    assert item.health_label == "HEALTH"
    assert item.distributions[0].format == "CSV"
    assert item.validation_results[0].ok is True
    assert item.validation_results[0].size_bytes == 123


async def test_collector_collect_url_route_can_skip_saving(monkeypatch):
    def fake_collect_source(url):
        return [
            CollectedDataset(
                dataset_url="https://catalog.example.org/dataset/mortality",
                title="Mortality health dataset",
                description="Official mortality health data.",
                publisher="National Health Agency",
                hosting_platform="",
                uploader="",
                geography=("France",),
                dataset_probability=0.92,
                dataset_signals={},
                health_probability=0.8,
                health_label="HEALTH",
                health_signals={},
                distributions=[],
                discovery_method="ckan",
                validation_results=[],
            )
        ]

    async def fake_save_collected_datasets(source_url, datasets):
        raise AssertionError("Should not save when save is false.")

    monkeypatch.setattr("app.routes.collector.collect_source", fake_collect_source)
    monkeypatch.setattr(
        "app.routes.collector.save_collected_datasets",
        fake_save_collected_datasets,
    )

    response = await collect_url(
        CollectorCollectURLRequest(url="https://catalog.example.org", save=False)
    )

    assert response.saved is False
    assert response.saved_count == 0
    assert len(response.items) == 1
    assert response.items[0].geography == ["France"]


async def test_collector_collect_url_route_returns_502_when_classification_fails(
    monkeypatch,
):
    def fake_collect_source(url):
        raise PageClassificationError("LLM classification failed.")

    monkeypatch.setattr("app.routes.collector.collect_source", fake_collect_source)

    try:
        await collect_url(CollectorCollectURLRequest(url="https://catalog.example.org"))
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Page classification failed."
    else:
        raise AssertionError("Expected HTTPException.")


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
                    dataset_probability=0.92,
                    dataset_signals={},
                    health_probability=0.8,
                    health_label="HEALTH",
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
                dataset_probability=0.92,
                dataset_signals={},
                health_probability=0.8,
                health_label="HEALTH",
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

    assert response.saved is False
    assert response.saved_count == 0
    assert len(response.items) == 1
    assert response.items[0].id == 7
    assert response.items[0].source_url == "https://catalog.example.org/"
    assert response.items[0].geography == ["France"]
    assert response.items[0].updated_at == "2026-08-16 12:00:00"
