"""Synthetic pages, validation outcomes and collected datasets shared by tests."""

from __future__ import annotations

from collector.classification.page import PageClassification
from collector.discovery.adapters import DiscoveredPage
from collector.main import collect_source_with_report
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

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

    return collect_source_with_report(
        "https://example.org",
        classifier=Accept(),
        discover=lambda _: [
            DiscoveredPage("https://example.org/dataset", "test", distributions=links)
        ],
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
