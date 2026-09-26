from __future__ import annotations

import io

import pytest

from collector.classification.page import PageClassification, PageClassificationError
from collector.config import CollectorConfig
from collector.discovery.adapters import DiscoveredPage
from collector.extraction.dataset_metadata import (
    DATASET_METADATA_KEYS,
    MISSING_DATASET_METADATA_VALUE,
)
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page, html_to_text
from collector.fetch import FetchedPage, PageFetchError
from collector.main import (
    analyze_discovered_page,
    analyze_html_page,
    collect_repository_candidate_with_report,
    collect_source_with_report,
)
from collector.storage.models import (
    CollectedDataset,
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
        )


class RejectingPageClassifier:
    def classify(self, page, distributions):
        return PageClassification(
            accepted=False,
            dataset_signals={"source": "test"},
        )


@pytest.mark.parametrize("repository_candidate", [False, True])
def test_collection_passes_config_to_network_operations(monkeypatch, repository_candidate):
    page_url = "https://example.org/datasets/mortality"
    file_url = "https://example.org/files/mortality.csv"
    html = f'<html><a href="{file_url}">Download CSV</a></html>'.encode()
    requests = []
    reads = []

    class Response(io.BytesIO):
        status = 200

        def __init__(self, request, body, headers):
            super().__init__(body)
            self.request = request
            self.headers = headers

        def geturl(self):
            return self.request.full_url

        def read(self, size=-1):
            reads.append((self.request.full_url, self.request.get_method(), size))
            return super().read(size)

    def open_response(request, *, timeout):
        requests.append((request, timeout))
        if request.full_url == page_url:
            return Response(request, html, {"Content-Type": "text/html"})
        assert request.full_url == file_url
        if request.get_method() == "HEAD":
            # Missing data headers force validation to sample the file with GET.
            return Response(request, b"", {})
        return Response(request, b"age,count\n" * 10_000, {"Content-Type": "text/csv"})

    monkeypatch.setattr("collector.fetch.open_public_http_url", open_response)
    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", open_response)

    # Consecutive runs must each bind their own settings, including a return
    # to defaults after custom configurations.
    for config in (
        CollectorConfig(
            request_timeout_seconds=3.0,
            max_sample_bytes=8_192,
            user_agent="TestCollector/2.0",
        ),
        CollectorConfig(
            request_timeout_seconds=1.5,
            max_sample_bytes=512,
            user_agent="TestCollector/3.0",
        ),
        CollectorConfig(),
    ):
        requests.clear()
        reads.clear()
        kwargs = {"config": config, "classifier": AcceptingPageClassifier()}
        if repository_candidate:
            result = collect_repository_candidate_with_report(page_url, **kwargs)
        else:
            result = collect_source_with_report(
                page_url,
                discover=lambda _: [DiscoveredPage(url=page_url, discovery_method="test")],
                **kwargs,
            )

        assert len(result.datasets) == 1
        assert result.datasets[0].validation_results[0].ok
        assert [
            (request.full_url, request.get_method(), timeout) for request, timeout in requests
        ] == [
            (page_url, "GET", config.request_timeout_seconds),
            (file_url, "HEAD", config.request_timeout_seconds),
            (file_url, "GET", config.request_timeout_seconds),
        ]
        assert requests[0][0].get_header("User-agent") == config.user_agent
        assert requests[2][0].get_header("Range") == f"bytes=0-{config.max_sample_bytes - 1}"
        assert reads == [
            (page_url, "GET", 1_000_001),
            (file_url, "GET", config.max_sample_bytes + 1),
        ]


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


@pytest.mark.parametrize(
    "canonical_href",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://other.example/dataset",
        "https://example.org:invalid/dataset",
    ],
)
def test_extract_page_falls_back_when_canonical_is_not_acceptable(canonical_href):
    page = extract_page(
        "https://example.org/catalog/page",
        f'<html><head><link rel="canonical" href="{canonical_href}"></head></html>',
    )

    assert page.canonical_url == "https://example.org/catalog/page"
    assert page.dataset_url == "https://example.org/catalog/page"


def test_analyze_discovered_page_rejects_invalid_url_before_classification():
    class ClassifierThatMustNotRun:
        def classify(self, page, distributions):
            raise AssertionError("The classifier must not receive an invalid URL.")

    result = analyze_discovered_page(
        DiscoveredPage(
            url="javascript:alert(1)",
            discovery_method="data_json",
            title="Invalid dataset",
        ),
        classifier=ClassifierThatMustNotRun(),
    )

    assert result is None


@pytest.mark.parametrize(
    "dataset_url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://example.org:invalid/dataset",
        "https://user@example.org/dataset",
    ],
)
def test_collected_dataset_rejects_invalid_dataset_url(dataset_url):
    with pytest.raises(ValueError, match=r"valid HTTP\(S\) URL"):
        CollectedDataset(
            dataset_url=dataset_url,
            title="Invalid dataset",
            description="",
            publisher="",
            hosting_platform="",
            uploader="",
            dataset_signals={},
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
    monkeypatch.setenv("RCP_DEEPSEEK_MODEL", "deepseek-test-model")
    monkeypatch.delenv("RCP_DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(PageClassificationError, match="RCP_DEEPSEEK_API_KEY"):
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
            )

    result = analyze_html_page(
        "https://example.org/data/catalog",
        DATASET_HTML,
        classifier=AcceptingClassifier(),
    )

    assert result is not None
    assert result.geography == ("France",)
    assert result.dataset_signals == {"source": "fake"}


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


def test_distribution_validation_samples_even_with_head_metadata():
    distribution = DistributionCandidate(
        url="https://example.org/files/mortality.csv",
        format="CSV",
        probability=0.9,
    )

    def fake_probe(url, **kwargs):
        return HTTPProbe(
            url=url,
            final_url=url,
            status_code=200,
            body_sample=b"country,value\nCH,10\n" if kwargs["method"] == "GET" else b"",
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


@pytest.mark.parametrize(
    ("resource_url", "initial_format", "content_type", "expected_format"),
    [
        ("https://example.org/api/mortality", "API", "application/json", "JSON"),
        ("https://example.org/download?id=123", "UNKNOWN", "text/csv", "CSV"),
    ],
)
def test_collect_source_retains_verified_distribution_format(
    resource_url, initial_format, content_type, expected_format,
):
    distribution = DistributionCandidate(
        url=resource_url,
        format=initial_format,
        probability=0.95,
        anchor="Download mortality data",
        signals={"schema_distribution": True},
    )

    def fake_probe(url, **kwargs):
        return HTTPProbe(
            url=url,
            final_url=f"https://data.example.org/mortality.{expected_format.lower()}",
            status_code=200,
            headers={"content-type": content_type},
            body_sample=b'{"data": [{"country": "CH"}]}' if expected_format == "JSON"
            else b"country,value\nCH,10\n",
        )

    result = collect_source_with_report(
        "https://example.org/catalog",
        discover=lambda _: [
            DiscoveredPage(
                url="https://example.org/datasets/mortality",
                discovery_method="data_json",
                title="Mortality health dataset",
                distributions=(distribution,),
            )
        ],
        validate=lambda candidate: validate_distribution(candidate, probe=fake_probe),
        classifier=AcceptingPageClassifier(),
    )

    assert len(result.datasets) == 1
    collected = result.datasets[0]
    retained = collected.distributions[0]
    validation = collected.validation_results[0]
    assert retained.format == validation.format == expected_format
    assert retained.url == validation.url == resource_url
    assert validation.ok is True
    assert retained.anchor == distribution.anchor
    assert retained.signals == distribution.signals
    assert distribution.format == initial_format


def test_collect_source_deduplicates_distributions_after_format_validation():
    resource_url = "https://example.org/api/mortality"

    def fake_probe(url, **kwargs):
        return HTTPProbe(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "application/json"},
            body_sample=b'{"data": [{"country": "CH"}]}',
        )

    result = collect_source_with_report(
        "https://example.org/catalog",
        config=CollectorConfig(max_distributions_saved=2),
        discover=lambda _: [
            DiscoveredPage(
                url="https://example.org/datasets/mortality",
                discovery_method="data_json",
                title="Mortality health dataset",
                distributions=(
                    DistributionCandidate(url=resource_url, format="API", probability=0.95),
                    DistributionCandidate(url=resource_url, format="JSON", probability=0.9),
                ),
            )
        ],
        validate=lambda candidate: validate_distribution(candidate, probe=fake_probe),
        classifier=AcceptingPageClassifier(),
    )

    collected = result.datasets[0]
    assert len(collected.distributions) == len(collected.validation_results) == 1
    assert collected.distributions[0].format == "JSON"
    assert collected.validation_results[0].format == "JSON"
    assert result.report.invalid_distribution_count == 0


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


def test_collect_repository_candidate_analyzes_only_the_candidate_page():
    candidate_url = "https://example.org/datasets/vaccination"

    def fake_fetch_html(url):
        assert url == candidate_url
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            html="""
            <html>
                <head><title>Vaccination health dataset</title></head>
                <body>
                    <p>Vaccination observations.</p>
                    <a href="/files/vaccination.csv">Download CSV</a>
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

    result = collect_repository_candidate_with_report(
        candidate_url,
        fetch_html=fake_fetch_html,
        validate=fake_validate,
        classifier=AcceptingPageClassifier(),
    )

    assert len(result.datasets) == 1
    assert result.datasets[0].dataset_url == candidate_url
    assert result.datasets[0].discovery_method == "repository_search"
    assert result.report.discovered_count == 1
    assert result.report.discovery_methods == ("repository_search",)


def test_collect_repository_candidate_propagates_page_fetch_errors():
    def fake_fetch_html(url):
        raise PageFetchError(f"Could not fetch URL: {url}")

    with pytest.raises(PageFetchError, match="Could not fetch URL"):
        collect_repository_candidate_with_report(
            "https://example.org/datasets/unavailable",
            fetch_html=fake_fetch_html,
            classifier=AcceptingPageClassifier(),
        )


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
