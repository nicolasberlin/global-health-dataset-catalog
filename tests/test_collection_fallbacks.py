from dataclasses import replace

import pytest

from collector.classification.page import PageClassification
from collector.config import CollectorConfig
from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage
from collector.main import collect_source_with_report
from collector.storage.models import DistributionCandidate, ValidationResult

PAGE_URL = "https://example.org/dataset/malaria"
FILE_URL = "https://example.org/malaria.csv"


class Classifier:
    def __init__(self):
        self.pages = []

    def classify(self, page, distributions):
        self.pages.append(page)
        assert distributions
        return PageClassification(accepted=True, dataset_signals={})


def available(distribution):
    return ValidationResult(distribution.url, distribution.url, distribution.format, True, 200)


@pytest.mark.parametrize("first_available", [0, 1, 2, 3, None])
def test_ranked_distinct_links_are_tried_until_success_or_three_attempts(first_available):
    links = [DistributionCandidate(f"https://example.org/{index}.csv", "CSV", .9 - index / 10)
             for index in range(4)]
    # Same URL with a different format must not consume a second attempt.
    duplicate = replace(links[0], format="API", probability=.85)
    discovered = DiscoveredPage(PAGE_URL, "ckan", title="Health data",
                                distributions=tuple(reversed([*links, duplicate])))
    probes = []
    classifier = Classifier()

    def validate(item):
        probes.append(item.url)
        result = available(item)
        if first_available is not None and item.url == links[first_available].url:
            return result
        return replace(result, status="unavailable", reason="Resource missing.")

    def no_fetch(url):
        pytest.fail("Structured data links should avoid the HTML request")

    result = collect_source_with_report(
        PAGE_URL, discover=lambda _: [discovered], fetch_html=no_fetch,
        classifier=classifier, validate=validate,
    )
    success = first_available is not None and first_available < 3
    attempts = first_available + 1 if success else 3
    assert probes == [item.url for item in links[:attempts]]
    assert len(classifier.pages) == 1
    assert result.report.invalid_distribution_count == attempts - int(success)
    assert len(result.report.validation_failures) == attempts - int(success)
    if success:
        saved_urls = [item.url for item in result.datasets[0].distributions]
        assert saved_urls == [links[first_available].url]
    else:
        assert result.datasets == []


def test_attempt_and_saved_limits_are_independent():
    links = tuple(DistributionCandidate(f"https://example.org/{i}.csv", "CSV", .9)
                  for i in range(5))
    probes = []

    def validate(item):
        probes.append(item.url)
        return available(item)

    result = collect_source_with_report(
        PAGE_URL, config=CollectorConfig(max_distribution_attempts=2, max_distributions_saved=3),
        discover=lambda _: [DiscoveredPage(PAGE_URL, "ckan", distributions=links)],
        classifier=Classifier(), validate=validate,
    )
    assert len(probes) == len(result.datasets[0].distributions) == 2


@pytest.mark.parametrize("conflicting_page_metadata", [False, True])
def test_metadata_without_downloads_is_merged_before_one_classification(conflicting_page_metadata):
    discovered = DiscoveredPage(
        PAGE_URL, "ckan", title="Malaria observations", description="Annual health data.",
        publisher="Health agency", geography=("Senegal",), date_of_publication="2020",
        sharing_license="CC-BY-4.0", diseases=("malaria",), size_of_dataset="100 rows",
        demographic_information=("age",), modality_of_data=("tabular",),
    )
    classifier = Classifier()
    fetches = []

    def fetch(url):
        assert not classifier.pages
        fetches.append(url)
        metadata = '''<title>Page title</title><script type="application/ld+json">
            {"@type":"Dataset","datePublished":"2021","license":"CC0"}</script>'''
        html = f'<html><head>{metadata if conflicting_page_metadata else ""}</head><body>'
        html += f'<a href="{FILE_URL}">Download CSV</a></body></html>'
        return FetchedPage(url, url, html, 200, "text/html")

    result = collect_source_with_report(
        PAGE_URL, discover=lambda _: [discovered], classifier=classifier,
        fetch_html=fetch, validate=available,
    )
    assert fetches == [PAGE_URL]
    assert len(classifier.pages) == 1
    page = classifier.pages[0]
    assert page.title == ("Page title" if conflicting_page_metadata else discovered.title)
    assert page.description_of_dataset == discovered.description
    assert page.publisher == discovered.publisher
    for field in ("geography", "diseases", "size_of_dataset",
                  "demographic_information", "modality_of_data"):
        assert getattr(page, field) == getattr(discovered, field)
    assert discovered.description in page.text
    dataset = result.datasets[0]
    assert dataset.discovery_method == "ckan"
    assert dataset.distributions[0].url == FILE_URL
    assert dataset.date_of_publication == ("2021" if conflicting_page_metadata else "2020")
    evidence = dataset.metadata_provenance["date_of_publication"]
    assert {entry["kind"] for entry in evidence} == (
        {"page", "adapter"} if conflicting_page_metadata else {"adapter"}
    )
    assert {entry["value"] for entry in evidence} == (
        {"2020", "2021"} if conflicting_page_metadata else {"2020"}
    )


@pytest.mark.parametrize("distribution", [
    None,
    DistributionCandidate("ftp://example.org/file.csv", "CSV", .9),
    DistributionCandidate("https://example.org/login", "HTML", .9),
    DistributionCandidate("https://example.org/api", "API", .9, mime_type="text/html"),
])
def test_title_or_unusable_links_fetch_page_but_no_downloads_skip_llm(distribution):
    classifier = Classifier()
    fetches = []
    discovered = DiscoveredPage(PAGE_URL, "ckan", title="Health data",
                                distributions=(distribution,) if distribution else ())

    def fetch(url):
        fetches.append(url)
        return FetchedPage(url, url, "<html>No files provided.</html>", 200, "text/html")

    result = collect_source_with_report(
        PAGE_URL, discover=lambda _: [discovered], classifier=classifier, fetch_html=fetch,
    )
    assert fetches == [PAGE_URL]
    assert classifier.pages == []
    assert result.datasets == []
    assert result.report.rejected_count == 1


def test_data_json_catalog_record_is_not_fetched_as_dataset_html():
    classifier = Classifier()
    catalog_url = "https://example.org/data.json"
    discovered = DiscoveredPage(
        catalog_url + "?identifier=malaria", "data_json", title="Malaria data",
        discovery_metadata={"data_json_url": catalog_url},
    )

    def no_fetch(url):
        pytest.fail("The catalog is not a dataset landing page")

    result = collect_source_with_report(
        catalog_url, discover=lambda _: [discovered], classifier=classifier, fetch_html=no_fetch,
    )
    assert classifier.pages == []
    assert result.datasets == []


def test_non_html_response_is_not_classified_as_a_page():
    classifier = Classifier()
    result = collect_source_with_report(
        PAGE_URL, discover=lambda _: [DiscoveredPage(PAGE_URL, "ckan", title="Health")],
        classifier=classifier,
        fetch_html=lambda url: FetchedPage(url, url, '{"title":"Health"}',
                                          200, "application/json"),
    )
    assert classifier.pages == []
    assert result.datasets == []
