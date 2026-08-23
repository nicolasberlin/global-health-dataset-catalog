from __future__ import annotations

import pytest

from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.classification.heuristic import HeuristicPageClassifier
from collector.classification.page import PageClassification, PageClassificationError
from collector.discovery.adapters import DiscoveredPage
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page, html_to_text
from collector.fetch import FetchedPage
from collector.main import analyze_html_page, collect_source, collect_source_with_report
from collector.storage.models import (
    DistributionCandidate,
    HTTPProbe,
    PageSnapshot,
    ValidationResult,
)
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


def test_dataset_score_rejects_catalog_page_with_only_weak_access_signals():
    page = PageSnapshot(
        url="https://example.org/catalog",
        canonical_url="https://example.org/catalog",
        title="WHO Data Catalogue",
        h1="Browse datasets and indicators",
        text="Browse our datasets and indicators catalogue. Download CSV resources from the API.",
    )
    distributions = [
        DistributionCandidate(
            url="https://example.org/catalog.csv",
            format="CSV",
            probability=0.9,
        )
    ]

    dataset_score = score_dataset_page(page, distributions)

    assert dataset_score.probability < 0.6
    assert dataset_score.signals["accepted_by_heuristics"] is False
    assert "catalog" in dataset_score.signals["catalog_concepts"]


def test_dataset_score_accepts_individual_dataset_without_structured_metadata():
    page = PageSnapshot(
        url="https://example.org/datasets/malaria-mortality",
        canonical_url="https://example.org/datasets/malaria-mortality",
        title="Global Malaria Mortality Estimates",
        h1="Mortality estimates dataset",
        meta_description="Annual malaria mortality estimates.",
        text="Download CSV data for this dataset.",
    )
    distributions = [
        DistributionCandidate(
            url="https://example.org/files/malaria-mortality.csv",
            format="CSV",
            probability=0.9,
        )
    ]

    dataset_score = score_dataset_page(page, distributions)

    assert dataset_score.probability >= 0.6
    assert dataset_score.signals["accepted_by_heuristics"] is True


def test_dataset_score_uses_whole_word_matching_for_access_terms():
    page = PageSnapshot(
        url="https://example.org/capital-projects",
        canonical_url="https://example.org/capital-projects",
        title="Capital projects",
        h1="Capital projects",
        text="Capital investments and office planning.",
    )

    dataset_score = score_dataset_page(page, [])

    assert dataset_score.probability == 0
    assert "access_concepts" not in dataset_score.signals


def test_dataset_score_treats_dcat_dataset_as_stronger_than_distribution():
    dataset_page = PageSnapshot(
        url="https://example.org/dataset",
        canonical_url="https://example.org/dataset",
        text='<div typeof="dcat:Dataset">Dataset metadata</div>',
    )
    distribution_page = PageSnapshot(
        url="https://example.org/catalog",
        canonical_url="https://example.org/catalog",
        text='<div typeof="dcat:Distribution">CSV resource</div>',
    )

    dataset_score = score_dataset_page(dataset_page, [])
    distribution_score = score_dataset_page(distribution_page, [])

    assert dataset_score.probability >= 0.6
    assert distribution_score.probability < 0.6


def test_dataset_score_recognizes_schema_org_dataset_url_type():
    page = PageSnapshot(
        url="https://example.org/dataset",
        canonical_url="https://example.org/dataset",
        json_ld=({"@type": "https://schema.org/Dataset"},),
    )

    dataset_score = score_dataset_page(page, [])

    assert dataset_score.probability >= 0.6
    assert dataset_score.signals["schema_dataset"] is True


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

    result = analyze_html_page(
        "https://example.org/about/careers",
        html,
        classifier=HeuristicPageClassifier(),
    )

    assert result is None


def test_analyze_html_page_uses_llm_default_classifier(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(PageClassificationError, match="OPENAI_API_KEY"):
        analyze_html_page("https://example.org/data/catalog", DATASET_HTML)


def test_heuristic_page_classifier_matches_existing_scores():
    page = extract_page("https://example.org/data/catalog", DATASET_HTML)
    distributions = extract_distributions(page)

    dataset_score = score_dataset_page(page, distributions)
    health_score = score_health_page(page)
    classification = HeuristicPageClassifier().classify(page, distributions)

    assert classification.accepted is True
    assert classification.dataset_probability == dataset_score.probability
    assert classification.dataset_signals == dataset_score.signals
    assert classification.health_probability == health_score.probability
    assert classification.health_label == health_score.label
    assert classification.health_signals == health_score.signals


def test_analyze_html_page_uses_injected_page_classifier():
    class AcceptingClassifier:
        def classify(self, page, distributions):
            assert page.canonical_url == "https://example.org/datasets/mortality"
            assert {distribution.format for distribution in distributions} == {
                "CSV",
                "API",
                "XLSX",
            }
            return PageClassification(
                accepted=True,
                dataset_probability=0.81,
                health_probability=0.77,
                health_label="HEALTH",
                dataset_signals={"source": "fake"},
                health_signals={"source": "fake"},
            )

    result = analyze_html_page(
        "https://example.org/data/catalog",
        DATASET_HTML,
        classifier=AcceptingClassifier(),
    )

    assert result is not None
    assert result.dataset_probability == 0.81
    assert result.dataset_signals == {"source": "fake"}
    assert result.health_probability == 0.77
    assert result.health_label == "HEALTH"
    assert result.health_signals == {"source": "fake"}


def test_analyze_html_page_respects_injected_page_classifier_rejection():
    class RejectingClassifier:
        def classify(self, page, distributions):
            return PageClassification(
                accepted=False,
                dataset_probability=0.95,
                health_probability=0.95,
                health_label="HEALTH",
            )

    result = analyze_html_page(
        "https://example.org/data/catalog",
        DATASET_HTML,
        classifier=RejectingClassifier(),
    )

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


def test_collect_source_uses_structured_discovery_metadata_without_fetching_html():
    csv_distribution = DistributionCandidate(
        url="https://data.example.org/mortality.csv",
        format="CSV",
        probability=0.95,
        mime_type="text/csv",
    )
    json_distribution = DistributionCandidate(
        url="https://data.example.org/mortality.json",
        format="JSON",
        probability=0.95,
        mime_type="application/json",
    )
    discovered_page = DiscoveredPage(
        url="https://catalog.example.org/dataset/mortality",
        discovery_method="ckan",
        priority=0.9,
        title="Mortality health dataset",
        description="Official epidemiology indicators.",
        publisher="National Health Agency",
        distributions=(csv_distribution, json_distribution),
    )

    def fake_discover(url):
        assert url == "https://catalog.example.org"
        return [discovered_page]

    def fake_fetch_html(url):
        raise AssertionError(f"Should not fetch structured discovery page: {url}")

    def fake_validate(distribution):
        return ValidationResult(
            url=distribution.url,
            final_url=distribution.url,
            format=distribution.format,
            ok=distribution.format == "CSV",
            http_status=200 if distribution.format == "CSV" else 500,
            mime_type=distribution.mime_type,
        )

    datasets = collect_source(
        "https://catalog.example.org",
        discover=fake_discover,
        fetch_html=fake_fetch_html,
        validate=fake_validate,
        classifier=HeuristicPageClassifier(),
    )

    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset.dataset_url == "https://catalog.example.org/dataset/mortality"
    assert dataset.title == "Mortality health dataset"
    assert dataset.publisher == "National Health Agency"
    assert dataset.discovery_method == "ckan"
    assert dataset.dataset_probability >= 0.6
    assert dataset.health_probability >= 0.35
    assert [distribution.url for distribution in dataset.distributions] == [
        "https://data.example.org/mortality.csv"
    ]
    assert [validation.ok for validation in dataset.validation_results] == [True]


def test_collect_source_falls_back_to_html_analysis_for_generic_discovery():
    discovered_page = DiscoveredPage(
        url="https://example.org/datasets/vaccination",
        discovery_method="generic_website",
        priority=0.1,
    )

    def fake_discover(url):
        assert url == "https://example.org/catalog"
        return [discovered_page]

    def fake_fetch_html(url):
        assert url == "https://example.org/datasets/vaccination"
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            html="""
            <html>
                <head>
                    <title>Vaccination health dataset</title>
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

    def fake_validate(distribution):
        return ValidationResult(
            url=distribution.url,
            final_url=distribution.url,
            format=distribution.format,
            ok=True,
            http_status=200,
            mime_type="text/csv",
        )

    datasets = collect_source(
        "https://example.org/catalog",
        discover=fake_discover,
        fetch_html=fake_fetch_html,
        validate=fake_validate,
        classifier=HeuristicPageClassifier(),
    )

    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset.discovery_method == "generic_website"
    assert dataset.title == "Vaccination health dataset"
    assert [distribution.format for distribution in dataset.distributions] == ["CSV"]
    assert dataset.validation_results[0].ok is True


def test_collect_source_with_report_summarizes_discovery_analysis_and_validation():
    mortality_distribution = DistributionCandidate(
        url="https://example.org/files/mortality.csv",
        format="CSV",
        probability=0.95,
        mime_type="text/csv",
    )
    cancer_distribution = DistributionCandidate(
        url="https://example.org/files/cancer.csv",
        format="CSV",
        probability=0.95,
        mime_type="text/csv",
    )
    discovered_pages = [
        DiscoveredPage(
            url="https://example.org/datasets/mortality",
            discovery_method="ckan",
            priority=0.9,
            title="Mortality health dataset",
            description="Official mortality and epidemiology indicators.",
            publisher="National Health Agency",
            distributions=(mortality_distribution,),
        ),
        DiscoveredPage(
            url="https://example.org/datasets/cancer",
            discovery_method="sitemap",
            priority=0.8,
            title="Cancer health dataset",
            description="Official cancer health data.",
            publisher="National Health Agency",
            distributions=(cancer_distribution,),
        ),
        DiscoveredPage(
            url="https://example.org/news/careers",
            discovery_method="sitemap",
            priority=0.1,
        ),
    ]

    def fake_discover(url):
        assert url == "https://example.org"
        return discovered_pages

    def fake_fetch_html(url):
        assert url == "https://example.org/news/careers"
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            html="""
            <html>
                <head><title>Careers and office news</title></head>
                <body><h1>Join our team</h1><p>Jobs and press events.</p></body>
            </html>
            """,
        )

    def fake_validate(distribution):
        return ValidationResult(
            url=distribution.url,
            final_url=distribution.url,
            format=distribution.format,
            ok=distribution.url == "https://example.org/files/mortality.csv",
            http_status=200,
            mime_type=distribution.mime_type,
        )

    result = collect_source_with_report(
        "https://example.org",
        discover=fake_discover,
        fetch_html=fake_fetch_html,
        validate=fake_validate,
        classifier=HeuristicPageClassifier(),
    )

    assert [dataset.dataset_url for dataset in result.datasets] == [
        "https://example.org/datasets/mortality"
    ]
    assert result.report.discovered_count == 3
    assert result.report.analyzed_count == 3
    assert result.report.accepted_count == 1
    assert result.report.rejected_count == 2
    assert result.report.invalid_distribution_count == 1
    assert result.report.discovery_methods == ("ckan", "sitemap")
