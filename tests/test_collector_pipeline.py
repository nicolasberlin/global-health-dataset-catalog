from __future__ import annotations

from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page, html_to_text
from collector.main import analyze_html_page
from collector.storage.models import DistributionCandidate, HTTPProbe
from collector.validation.downloads import validate_distribution

DATASET_HTML = """
<!doctype html>
<html>
    <head>
        <title>Mortality by age and sex dataset</title>
        <link rel="canonical" href="/datasets/mortality" />
        <meta name="description" content="Official mortality health dataset." />
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": "Mortality by age and sex",
            "publisher": {"@type": "Organization", "name": "National Health Agency"},
            "distribution": [
                {
                    "@type": "DataDownload",
                    "contentUrl": "https://example.org/files/mortality.csv",
                    "encodingFormat": "text/csv"
                }
            ]
        }
        </script>
    </head>
    <body>
        <main>
            <h1>Mortality by age and sex</h1>
            <h2>Downloads</h2>
            <p>This dataset contains mortality and epidemiology indicators.</p>
            <a href="/files/mortality.xlsx">Download data as XLSX</a>
            <a href="/api/export?dataset=mortality&format=json">API export</a>
            <a href="/files/report.pdf">Methodology PDF</a>
        </main>
    </body>
</html>
"""


def test_collector_extracts_and_scores_health_dataset_page():
    page = extract_page("https://example.org/data/catalog", DATASET_HTML)

    assert page.canonical_url == "https://example.org/datasets/mortality"
    assert page.title == "Mortality by age and sex dataset"
    assert page.h1 == "Mortality by age and sex"
    assert page.publisher == "National Health Agency"
    assert len(page.links) == 3

    distributions = extract_distributions(page)
    assert {distribution.format for distribution in distributions} == {"API", "CSV", "XLSX"}
    assert all(
        distribution.url != "https://example.org/files/report.pdf"
        for distribution in distributions
    )

    dataset_score = score_dataset_page(page, distributions)
    health_score = score_health_page(page)

    assert dataset_score.probability >= 0.9
    assert dataset_score.signals["schema_dataset"] is True
    assert health_score.probability >= 0.75
    assert health_score.label == "HEALTH"


def test_collector_cleans_html_descriptions():
    html = """
    <html>
        <head>
            <title>Household air pollution</title>
            <meta
                name="description"
                content="<p><strong>Goal 7</strong>&nbsp;Exposure to indoor air pollutants.</p>"
            />
        </head>
        <body><h1>Household air pollution</h1></body>
    </html>
    """

    page = extract_page("https://example.org/household-air-pollution", html)

    assert page.meta_description == "Goal 7 Exposure to indoor air pollutants."
    assert html_to_text("<p>Mortality&nbsp;<strong>dataset</strong></p>") == "Mortality dataset"


def test_collector_identifies_known_publisher_from_domain():
    page = extract_page(
        "https://www.who.int/data/gho/data/themes/air-pollution/household-air-pollution",
        "<html><head><title>Household air pollution</title></head><body></body></html>",
    )

    assert page.publisher == "World Health Organization"
    assert page.hosting_platform == ""
    assert page.uploader == ""


def test_collector_identifies_kaggle_platform_and_uploader():
    page = extract_page(
        "https://www.kaggle.com/datasets/prasad22/healthcare-dataset",
        "<html><head><title>Healthcare Dataset</title></head><body></body></html>",
    )

    assert page.publisher == ""
    assert page.hosting_platform == "Kaggle"
    assert page.uploader == "prasad22"


def test_collector_scores_healthcare_title_as_partial_health():
    page = extract_page(
        "https://www.kaggle.com/datasets/prasad22/healthcare-dataset",
        """
        <html>
            <head><title>Healthcare Dataset | Kaggle</title></head>
            <body><h1>Healthcare Dataset</h1></body>
        </html>
        """,
    )

    health_score = score_health_page(page)

    assert health_score.probability >= 0.35
    assert health_score.label == "PARTIALLY_HEALTH"
    assert "healthcare" in health_score.signals["matched_keywords"]


def test_collector_rejects_non_health_non_dataset_page():
    html = """
    <html>
        <head><title>Careers and office news</title></head>
        <body>
            <h1>Join our team</h1>
            <p>Press events, careers, office contact information.</p>
            <a href="/jobs">Open roles</a>
        </body>
    </html>
    """

    result = analyze_html_page("https://example.org/about/careers", html)

    assert result is None


def test_distribution_validation_uses_head_metadata():
    distribution = DistributionCandidate(
        url="https://example.org/files/mortality.csv",
        format="CSV",
        probability=0.9,
    )

    def fake_probe(url, **kwargs):
        assert kwargs["method"] == "HEAD"
        return HTTPProbe(
            url=url,
            final_url=url,
            status_code=200,
            headers={
                "content-type": "text/csv",
                "content-length": "12345",
                "etag": '"abc"',
                "last-modified": "Sat, 15 Aug 2026 10:00:00 GMT",
            },
        )

    result = validate_distribution(distribution, probe=fake_probe)

    assert result.ok is True
    assert result.http_status == 200
    assert result.mime_type == "text/csv"
    assert result.size_bytes == 12345
    assert result.format == "CSV"


def test_distribution_validation_falls_back_to_partial_get():
    distribution = DistributionCandidate(
        url="https://example.org/download?id=123",
        format="UNKNOWN",
        probability=0.6,
    )
    calls: list[str] = []

    def fake_probe(url, **kwargs):
        calls.append(kwargs["method"])
        if kwargs["method"] == "HEAD":
            return HTTPProbe(
                url=url,
                final_url=url,
                status_code=405,
                headers={},
                error="405 Method Not Allowed",
            )
        return HTTPProbe(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "application/octet-stream"},
            body_sample=b"country,mortality\\nGBR,10\\n",
        )

    result = validate_distribution(distribution, probe=fake_probe)

    assert calls == ["HEAD", "GET"]
    assert result.ok is True
    assert result.format == "CSV"
