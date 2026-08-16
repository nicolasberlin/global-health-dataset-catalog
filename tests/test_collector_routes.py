from __future__ import annotations

from app.routes.collector import (
    CollectorAnalyzeHTMLRequest,
    CollectorAnalyzeURLRequest,
    CollectorCollectURLRequest,
    CollectorDiscoverURLRequest,
    analyze_html,
    analyze_url,
    collect_url,
    discover_url,
    list_collected,
)
from fastapi import HTTPException

from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult


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
