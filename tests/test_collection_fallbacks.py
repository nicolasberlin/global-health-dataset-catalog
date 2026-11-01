from dataclasses import replace

import pytest
from helpers.collection import collect_record_page

from collector.collection.contracts import DiscoveredPage
from collector.collection.eligibility.models import PageClassification
from collector.collection.service import collect_repository_candidate_with_report
from collector.config import CollectorConfig
from collector.models import DistributionCandidate, ValidationResult
from collector.network.fetch import FetchedPage

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

    result = collect_record_page(
        discovered, fetch_html=no_fetch, classifier=classifier, validate=validate
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

    result = collect_record_page(
        DiscoveredPage(PAGE_URL, "ckan", distributions=links),
        config=CollectorConfig(max_distribution_attempts=2, max_distributions_saved=3),
        classifier=Classifier(),
        validate=validate,
    )
    assert len(probes) == len(result.datasets[0].distributions) == 2


def test_non_html_response_is_not_classified_as_a_page():
    classifier = Classifier()
    result = collect_repository_candidate_with_report(
        PAGE_URL, classifier=classifier,
        fetch_html=lambda url: FetchedPage(
            url, url, '{"title":"Health"}', 200, "application/json",
        ),
    )
    assert classifier.pages == []
    assert result.datasets == []
    assert not result.report.verification_complete
    assert result.report.errors[0].code == "verification_unconfirmed"
