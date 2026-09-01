from __future__ import annotations

import pytest

from collector.classification.page import PageClassification, PageClassificationError
from collector.discovery.adapters import DiscoveredPage
from collector.extraction.dataset_metadata import (
    DATASET_METADATA_KEYS,
    MISSING_DATASET_METADATA_VALUE,
)
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page, html_to_text
from collector.fetch import FetchedPage
from collector.main import analyze_html_page, collect_source_with_report
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
            "spatialCoverage": {"@type": "Country", "name": "France"},
            "datePublished": "2025-05-01",
            "license": "CC-BY-4.0",
            "contentSize": "12,000 records",
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


class AcceptingPageClassifier:
    def classify(self, page, distributions):
        return PageClassification(
            accepted=True,
            dataset_signals={"source": "test"},
            health_signals={"source": "test"},
        )


class RejectingPageClassifier:
    def classify(self, page, distributions):
        return PageClassification(
            accepted=False,
            dataset_signals={"source": "test"},
            health_signals={"source": "test"},
        )


def test_collector_extracts_dataset_page_and_distributions():
    page = extract_page("https://example.org/data/catalog", DATASET_HTML)

    assert page.canonical_url == "https://example.org/datasets/mortality"
    assert page.title == "Mortality by age and sex dataset"
    assert page.h1 == "Mortality by age and sex"
    assert page.publisher == "National Health Agency"
    assert page.geography == ("France",)
    assert len(page.links) == 3

    distributions = extract_distributions(page)
    assert {distribution.format for distribution in distributions} == {"API", "CSV", "XLSX"}
    assert all(
        distribution.url != "https://example.org/files/report.pdf"
        for distribution in distributions
    )

def test_extract_page_builds_normalized_business_metadata():
    page = extract_page("https://example.org/data/catalog", DATASET_HTML)

    assert page.geography == ("France",)
    assert page.date_of_publication == "2025-05-01"
    assert page.dataset_url == "https://example.org/datasets/mortality"
    assert page.diseases == ()
    assert page.size_of_dataset == "12,000 records"
    assert page.demographic_information == ("age", "sex")
    assert page.sharing_license == "CC-BY-4.0"
    assert page.modality_of_data == ("tabular",)
    assert page.description_of_dataset == "Official mortality health dataset."
    assert page.dataset_metadata() == {
        "Title": "Mortality by age and sex dataset",
        "Geography": "France",
        "Date of publication": "2025-05-01",
        "Dataset URL": "https://example.org/datasets/mortality",
        "Disease(s)": MISSING_DATASET_METADATA_VALUE,
        "Size of dataset": "12,000 records",
        "Demographic information": "age, sex",
        "Sharing license": "CC-BY-4.0",
        "Modality of data": "tabular",
        "Description of dataset": "Official mortality health dataset.",
    }


def test_extract_page_uses_na_for_missing_business_metadata():
    page = extract_page(
        "https://example.org/minimal",
        "<html><body><p>No dataset metadata here.</p></body></html>",
    )

    assert page.geography == ()
    assert page.date_of_publication == ""
    assert page.diseases == ()
    assert page.size_of_dataset == ""
    assert page.demographic_information == ()
    assert page.sharing_license == ""
    assert page.modality_of_data == ()
    assert page.description_of_dataset == ""
    assert page.dataset_metadata()["Dataset URL"] == "https://example.org/minimal"
    assert all(
        value == MISSING_DATASET_METADATA_VALUE
        for key, value in page.dataset_metadata().items()
        if key != "Dataset URL"
    )


def test_extract_page_does_not_substitute_modified_or_method_for_publication_or_size():
    page = extract_page(
        "https://example.org/dataset",
        """
        <html>
            <head>
                <script type="application/ld+json">
                {
                    "@type": "Dataset",
                    "dateModified": "2026-01-01",
                    "measurementTechnique": "Household survey",
                    "description": "Mortality and vaccination statistics."
                }
                </script>
            </head>
            <body><p>Mortality and vaccination statistics.</p></body>
        </html>
        """,
    )

    assert page.date_of_publication == ""
    assert page.size_of_dataset == ""
    assert page.diseases == ()
    assert page.dataset_metadata()["Date of publication"] == MISSING_DATASET_METADATA_VALUE
    assert page.dataset_metadata()["Size of dataset"] == MISSING_DATASET_METADATA_VALUE
    assert page.dataset_metadata()["Disease(s)"] == MISSING_DATASET_METADATA_VALUE


def test_page_snapshot_exports_business_metadata_contract_without_storing_a_copy():
    page = PageSnapshot(
        url="https://example.org/record",
        canonical_url="https://example.org/record",
        title="Mortality dataset",
        geography=(" France ", "France"),
    )

    assert not hasattr(page, "metadata")
    assert tuple(page.dataset_metadata()) == DATASET_METADATA_KEYS
    assert page.dataset_metadata()["Title"] == "Mortality dataset"
    assert page.title == "Mortality dataset"
    assert page.dataset_metadata()["Geography"] == "France"
    assert page.geography == ("France",)


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
        classifier=RejectingPageClassifier(),
    )

    assert result is None


def test_analyze_html_page_uses_llm_default_classifier(monkeypatch):
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_1", "model-a")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_2", "model-b")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_3", "model-c")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(PageClassificationError, match="OPENAI_API_KEY"):
        analyze_html_page("https://example.org/data/catalog", DATASET_HTML)


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
                dataset_signals={"source": "fake"},
                health_signals={"source": "fake"},
            )

    result = analyze_html_page(
        "https://example.org/data/catalog",
        DATASET_HTML,
        classifier=AcceptingClassifier(),
    )

    assert result is not None
    assert result.geography == ("France",)
    assert result.dataset_signals == {"source": "fake"}
    assert result.health_signals == {"source": "fake"}


def test_analyze_html_page_respects_injected_page_classifier_rejection():
    class RejectingClassifier:
        def classify(self, page, distributions):
            return PageClassification(accepted=False)

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
        geography=("France",),
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

    result = collect_source_with_report(
        "https://catalog.example.org",
        discover=fake_discover,
        fetch_html=fake_fetch_html,
        validate=fake_validate,
        classifier=AcceptingPageClassifier(),
    )
    datasets = result.datasets

    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset.dataset_url == "https://catalog.example.org/dataset/mortality"
    assert dataset.title == "Mortality health dataset"
    assert dataset.publisher == "National Health Agency"
    assert dataset.geography == ("France",)
    assert dataset.discovery_method == "ckan"
    assert [distribution.url for distribution in dataset.distributions] == [
        "https://data.example.org/mortality.csv"
    ]
    assert [validation.ok for validation in dataset.validation_results] == [True]


def test_collect_source_falls_back_to_html_analysis_for_generic_discovery():
    discovered_page = DiscoveredPage(
        url="https://example.org/datasets/vaccination",
        discovery_method="generic_website",
        priority=0.1,
        geography=("Germany",),
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

    result = collect_source_with_report(
        "https://example.org/catalog",
        discover=fake_discover,
        fetch_html=fake_fetch_html,
        validate=fake_validate,
        classifier=AcceptingPageClassifier(),
    )
    datasets = result.datasets

    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset.discovery_method == "generic_website"
    assert dataset.title == "Vaccination health dataset"
    assert dataset.geography == ("Germany",)
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
        classifier=AcceptingPageClassifier(),
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
