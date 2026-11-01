"""Synthetic pages, validation outcomes and collected datasets shared by tests."""

from __future__ import annotations

from collector.collection.contracts import ResolvedPage
from collector.collection.eligibility.models import PageClassification
from collector.collection.service import collect_repository_candidate_with_report
from collector.models import CollectedDataset, DistributionCandidate, ValidationResult

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


class Accept:
    def classify(self, page, distributions):
        return PageClassification(accepted=True)


def collect_record_page(page, *, config=None, validate=None, classifier=None,
                        fetch_html=None, browser=None):
    """Run real record collection with a synthetic metadata connector, never live discovery."""
    from types import SimpleNamespace

    from collector.collection.records import NormalizedRecord, RecordIdentity
    from collector.config import DEFAULT_CONFIG
    from collector.network.fetch import FetchedPage

    identity = RecordIdentity("fixture", "https://example.org", "dataset", page.url)

    class Connector:
        name = "fixture"
        method = "fixture_api"

        def reference_identity(self, url):
            return identity

        def normalize(self, url, payload):
            return NormalizedRecord(
                identity=identity, landing_url=page.url,
                metadata_source_url=page.url, title=page.title or "Health data",
                description=page.description, publisher=page.publisher,
                publication_date=page.date_of_publication, license=page.sharing_license,
                doi=page.doi, resources=page.distributions,
            )

        def scope_resources(self, url, resources, known_record=None):
            return resources

    class Registry:
        def select(self, url):
            return SimpleNamespace(connector=Connector(), api_url=page.url)

    return collect_repository_candidate_with_report(
        page.url, config=config or DEFAULT_CONFIG,
        classifier=classifier or Accept(), validate=validate,
        fetch_json=lambda _: {}, registry=Registry(), browser=browser,
        fetch_html=fetch_html or (lambda url: FetchedPage(url, url, "", 200, "text/html")),
    )


def collect(validations):
    links = tuple(
        DistributionCandidate(f"https://example.org/{i}.csv", "CSV", 0.9)
        for i in range(len(validations))
    )
    results = iter(validations)

    def validate(item):
        status = next(results)
        return ValidationResult(
            item.url, item.url, "CSV", status == "available", 200, status=status
        )

    return collect_record_page(
        ResolvedPage("https://example.org/dataset", "fixture_api", distributions=links),
        classifier=Accept(),
        validate=validate,
    )


def mortality_dataset() -> CollectedDataset:
    return CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/mortality",
        title="Mortality health dataset",
        description="Official mortality health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        geography=("France",),
        dataset_signals={"schema_dataset": True},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/mortality.csv",
                format="CSV",
                probability=0.95,
                anchor="CSV download",
                mime_type="text/csv",
                signals={"ckan_resource": True},
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
