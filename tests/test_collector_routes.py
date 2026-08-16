from __future__ import annotations

from app.routes.collector import (
    CollectorAnalyzeHTMLRequest,
    CollectorAnalyzeURLRequest,
    CollectorCollectionJobRequest,
    CollectorCollectURLRequest,
    CollectorDiscoverURLRequest,
    _run_collection_job,
    analyze_html,
    analyze_url,
    collect_url,
    discover_url,
    list_collected,
    read_collection_job,
    start_collection_job,
)
from fastapi import BackgroundTasks, HTTPException

from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    ValidationResult,
)


def test_collector_analyze_html_route_returns_scores_and_distributions():
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

    response = analyze_html(payload)

    assert response.accepted is True
    assert response.publisher == "National Health Agency"
    assert response.hosting_platform == ""
    assert response.uploader == ""
    assert response.dataset_probability >= 0.9
    assert response.health_probability >= 0.35
    assert response.health_label in {"HEALTH", "PARTIALLY_HEALTH"}
    assert {distribution.format for distribution in response.distributions} == {"CSV", "XLSX"}


def test_collector_analyze_url_route_fetches_and_analyzes_html(monkeypatch):
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

    response = analyze_url(CollectorAnalyzeURLRequest(url="https://example.org/catalog"))

    assert response.accepted is True
    assert response.publisher == ""
    assert response.hosting_platform == ""
    assert response.uploader == ""
    assert response.dataset_probability >= 0.6
    assert response.health_probability >= 0.35
    assert {distribution.format for distribution in response.distributions} == {"CSV"}


def test_collector_discover_url_route_returns_discovered_pages(monkeypatch):
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
                metadata={"ckan_name": "mortality"},
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

    response = discover_url(CollectorDiscoverURLRequest(url="https://catalog.example.org"))

    assert len(response.items) == 1
    item = response.items[0]
    assert item.url == "https://catalog.example.org/dataset/mortality"
    assert item.discovery_method == "ckan"
    assert item.priority == 0.9
    assert item.title == "Mortality dataset"
    assert item.description == "Official mortality health data."
    assert item.publisher == "National Health Agency"
    assert item.metadata == {"ckan_name": "mortality"}
    assert len(item.distributions) == 1
    assert item.distributions[0].url == "https://catalog.example.org/files/mortality.csv"
    assert item.distributions[0].format == "CSV"
    assert item.distributions[0].mime_type == "text/csv"


def test_collector_discover_url_route_returns_bad_request_for_discovery_errors(monkeypatch):
    def fake_discover_source(url):
        raise ValueError(f"Could not discover {url}")

    monkeypatch.setattr("app.routes.collector.discover_source", fake_discover_source)

    try:
        discover_url(CollectorDiscoverURLRequest(url="https://catalog.example.org"))
    except HTTPException as exception:
        assert exception.status_code == 400
        assert exception.detail == "Could not discover https://catalog.example.org/"
    else:
        raise AssertionError("Expected HTTPException.")


def test_collector_collect_url_route_returns_collected_datasets(monkeypatch):
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

    def fake_save_collected_datasets(source_url, datasets):
        saved_calls.append((source_url, datasets))
        return datasets

    monkeypatch.setattr("app.routes.collector.collect_source", fake_collect_source)
    monkeypatch.setattr(
        "app.routes.collector.save_collected_datasets",
        fake_save_collected_datasets,
    )

    response = collect_url(CollectorCollectURLRequest(url="https://catalog.example.org"))

    assert len(saved_calls) == 1
    assert saved_calls[0][0] == "https://catalog.example.org/"
    assert len(response.items) == 1
    assert response.saved is True
    assert response.saved_count == 1
    item = response.items[0]
    assert item.dataset_url == "https://catalog.example.org/dataset/mortality"
    assert item.discovery_method == "ckan"
    assert item.dataset_probability == 0.92
    assert item.health_label == "HEALTH"
    assert item.distributions[0].format == "CSV"
    assert item.validation_results[0].ok is True
    assert item.validation_results[0].size_bytes == 123


def test_collector_collect_url_route_can_skip_saving(monkeypatch):
    def fake_collect_source(url):
        return [
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
        ]

    def fake_save_collected_datasets(source_url, datasets):
        raise AssertionError("Should not save when save is false.")

    monkeypatch.setattr("app.routes.collector.collect_source", fake_collect_source)
    monkeypatch.setattr(
        "app.routes.collector.save_collected_datasets",
        fake_save_collected_datasets,
    )

    response = collect_url(
        CollectorCollectURLRequest(url="https://catalog.example.org", save=False)
    )

    assert response.saved is False
    assert response.saved_count == 0
    assert len(response.items) == 1


def test_collector_start_collection_job_route_enqueues_background_task(monkeypatch):
    def fake_create_collection_job(source_url):
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

    response = start_collection_job(
        CollectorCollectionJobRequest(url="https://catalog.example.org"),
        background_tasks,
    )

    assert response.job.id == 12
    assert response.job.status == "pending"
    assert len(background_tasks.tasks) == 1


def test_collector_read_collection_job_route_returns_status(monkeypatch):
    def fake_get_collection_job(job_id):
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

    response = read_collection_job(12)

    assert response.job.id == 12
    assert response.job.status == "done"
    assert response.job.saved_count == 2
    assert response.job.discovered_count == 10
    assert response.job.discovery_methods == ["sitemap"]


def test_collector_read_collection_job_route_returns_not_found(monkeypatch):
    monkeypatch.setattr("app.routes.collector.get_collection_job", lambda job_id: None)

    try:
        read_collection_job(404)
    except HTTPException as exception:
        assert exception.status_code == 404
        assert exception.detail == "Collection job not found"
    else:
        raise AssertionError("Expected HTTPException.")


def test_run_collection_job_marks_done(monkeypatch):
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

    def fake_save_collected_datasets(source_url, datasets):
        calls.append(("save", source_url, len(datasets)))
        return datasets

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        lambda job_id: calls.append(("running", job_id)),
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
        lambda job_id, saved_count, report: calls.append(
            ("done", job_id, saved_count, report.discovered_count, report.discovery_methods)
        ),
    )

    _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [
        ("running", 12),
        ("collect", "https://catalog.example.org/"),
        ("save", "https://catalog.example.org/", 1),
        ("done", 12, 1, 5, ("ckan",)),
    ]


def test_run_collection_job_marks_errors(monkeypatch):
    calls = []

    def fake_collect_source_with_report(source_url):
        raise ValueError("bad source")

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        lambda job_id: calls.append(("running", job_id)),
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_error",
        lambda job_id, error: calls.append(("error", job_id, error)),
    )

    _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [("running", 12), ("error", 12, "bad source")]


def test_collector_list_collected_route_returns_saved_datasets(monkeypatch):
    def fake_list_collected_datasets():
        return [
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
                source_url="https://catalog.example.org/",
                database_id=7,
                updated_at="2026-08-16 12:00:00",
            )
        ]

    monkeypatch.setattr(
        "app.routes.collector.list_collected_datasets",
        fake_list_collected_datasets,
    )

    response = list_collected()

    assert response.saved is False
    assert response.saved_count == 0
    assert len(response.items) == 1
    assert response.items[0].id == 7
    assert response.items[0].source_url == "https://catalog.example.org/"
    assert response.items[0].updated_at == "2026-08-16 12:00:00"
