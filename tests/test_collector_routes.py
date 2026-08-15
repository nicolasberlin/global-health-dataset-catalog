from __future__ import annotations

from app.routes.collector import (
    CollectorAnalyzeHTMLRequest,
    CollectorAnalyzeURLRequest,
    analyze_html,
    analyze_url,
)

from collector.fetch import FetchedPage


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
