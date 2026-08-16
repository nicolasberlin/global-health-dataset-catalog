from __future__ import annotations

from app.routes.collector import (
    CollectorAnalyzeHTMLRequest,
    CollectorAnalyzeURLRequest,
    CollectorDiscoverURLRequest,
    analyze_html,
    analyze_url,
    discover_url,
)
from fastapi import HTTPException

from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage
from collector.storage.models import DistributionCandidate


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
