from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import pytest

from collector.budget import collection_budget
from collector.classification.page import PageClassification
from collector.collection.contracts import public_url
from collector.collection.service import collect_repository_candidate_with_report
from collector.collection.strategies.dataverse import record_api_url, resolve_metadata
from collector.config import DEFAULT_CONFIG
from collector.network.fetch import FetchedPage, PageFetchError
from collector.storage.models import ValidationResult
from collector.validation.downloads import page_access_diagnostic

URL = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi%3A10.7910%2FDVN%2FMGQGKG"
BARRIER = Path("tests/fixtures/collection/harvard-verification.html").read_text()


class Accept:
    def classify(self, page, distributions):
        return PageClassification(True)


def html(body, status=200):
    return FetchedPage(URL, URL, body, status, "text/html")


def available(resource):
    return ValidationResult(
        resource.url, resource.url, resource.format, True, 206, mime_type=resource.mime_type
    )


def metadata(count=1):
    return {
        "status": "OK",
        "data": {
            "latestVersion": {
                "metadataBlocks": {
                    "citation": {"fields": [{"typeName": "title", "value": "HIV data"}]}
                },
                "files": [
                    {
                        "dataFile": {
                            "id": n + 1,
                            "filename": f"data-{n}.csv",
                            "contentType": "text/csv",
                        }
                    }
                    for n in range(count)
                ],
            }
        },
    }


def denied(_):
    try:
        raise HTTPError(URL, 403, "Forbidden", {}, None)
    except HTTPError as error:
        raise ValueError("Metadata access refused") from error


class Browser:
    def __init__(self, count=1):
        self.count, self.calls = count, []

    def render(self, url, metadata_url=None):
        self.calls.append("render")
        return resolve_metadata(url, metadata(self.count))

    def validate(self, resource):
        self.calls.append("validate")
        return available(resource)


def test_api_links_are_validated_before_stopping_and_coverage_is_bounded():
    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=lambda _: metadata(5),
        fetch_html=lambda _: pytest.fail("HTML should not be fetched"),
        validate=available,
        classifier=Accept(),
    )
    assert len(result.datasets[0].distributions) == 1
    assert result.report.coverage == {
        "policy": "bounded_validated_resources",
        "max_saved": 1,
        "max_checks": 3,
        "discovered": 5,
        "checked": 1,
        "validated": 1,
        "discovery": "listed",
        "limited": True,
    }
    assert result.report.method_attempts[0]["checks"][0]["status"] == "available"


def test_api_failure_recovered_by_html_is_history_not_fatal_outcome():
    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=denied,
        fetch_html=lambda _: html(
            '<html><title>HIV data</title><a href="/data.csv">CSV</a></html>'
        ),
        validate=available,
        classifier=Accept(),
    )
    assert result.datasets and not result.report.errors
    assert [a["status"] for a in result.report.method_attempts] == ["failed", "succeeded"]
    assert result.report.method_attempts[0]["http_status"] == 403


def test_harvard_challenge_is_incomplete_without_browser():
    result = collect_repository_candidate_with_report(URL, fetch_html=lambda _: html(BARRIER, 202))
    assert not result.datasets and not result.report.verification_complete
    assert result.report.errors[0].code == "verification_unconfirmed"
    assert result.report.rejected_count == 0


def test_challenge_is_recovered_by_browser_and_uses_its_validator():
    browser = Browser()
    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=denied,
        fetch_html=lambda _: html(BARRIER, 202),
        browser=browser,
        classifier=Accept(),
        validate=lambda _: pytest.fail("Resource needs the browser session"),
    )
    assert result.datasets and not result.report.errors
    assert browser.calls == ["render", "validate"]
    assert [a["method"] for a in result.report.method_attempts] == [
        "dataverse_api",
        "html",
        "browser",
    ]


def test_an_ordinary_javascript_mention_is_not_an_access_barrier():
    assert (
        page_access_diagnostic("<html><p>Our documentation discusses JavaScript.</p></html>")
        is None
    )


def test_empty_official_listing_stops_without_unnecessary_navigation():
    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=lambda _: metadata(0),
        fetch_html=lambda _: pytest.fail("Authoritative listing was empty"),
    )
    assert not result.datasets and result.report.verification_complete
    assert result.report.method_attempts[0]["code"] == "no_download_links"


def test_file_record_never_broadens_to_the_parent_dataset():
    url = "https://dataverse.harvard.edu/file.xhtml?fileId=123&version=1.0"
    assert record_api_url(url, DEFAULT_CONFIG.dataverse_hosts) == (
        "https://dataverse.harvard.edu/api/v1/files/123/versions/1.0"
    )
    result = resolve_metadata(
        url,
        {
            "status": "OK",
            "data": {
                "dataFile": {
                    "id": 123,
                    "filename": "sample.tab",
                    "contentType": "text/tab-separated-values",
                }
            },
        },
    )
    assert len(result.page.distributions) == 1
    assert result.page.distributions[0].format == "TSV"
    assert (
        result.page.distributions[0].signals["resource_key"]
        == "dataverse:dataverse.harvard.edu:file:123"
    )


def test_pinned_dataset_version_does_not_resolve_the_latest_listing():
    assert record_api_url(URL + "&version=1.0", DEFAULT_CONFIG.dataverse_hosts) is None


@pytest.mark.parametrize("data", [{}, {"latestVersion": {}}, {"latestVersion": {"files": [None]}}])
def test_incomplete_or_malformed_api_listing_is_not_authoritative_empty(data):
    with pytest.raises(ValueError):
        resolve_metadata(URL, {"status": "OK", "data": data})


def test_supported_methods_do_not_start_after_the_shared_deadline():
    with collection_budget(seconds=-1):
        result = collect_repository_candidate_with_report(
            URL, fetch_html=lambda _: pytest.fail("Already expired")
        )
    assert result.report.errors[0].code == "collection_budget_exhausted"


def test_distinct_file_checks_share_one_limit_across_methods():
    calls = []

    def invalid(resource):
        calls.append(resource.url)
        return ValidationResult(resource.url, resource.url, "CSV", False, 403)

    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=lambda _: metadata(4),
        fetch_html=lambda _: html('<html><a href="/other.csv">CSV</a></html>'),
        validate=invalid,
        classifier=Accept(),
    )
    assert len(calls) == 3
    assert not result.report.verification_complete
    assert result.report.coverage["limited"]


def test_valid_classification_rejection_is_not_retried_for_a_positive_vote():
    class Reject:
        def classify(self, *args):
            return PageClassification(False)

    browser = Browser()
    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=lambda _: metadata(),
        fetch_html=lambda _: pytest.fail("A valid rejection stops processing"),
        classifier=Reject(),
        browser=browser,
    )
    assert not result.datasets and not browser.calls
    assert result.report.method_attempts[0]["code"] == "page_rejected"


def test_diagnostic_urls_remove_access_credentials():
    assert (
        public_url("https://user:secret@example.org/file;jsessionid=secret?token=x&fileId=123")
        == "https://example.org/file;jsessionid=[redacted]?fileId=123"
    )


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://user:secret@[2001:db8::1]:8443/file?token=secret&id=123#private",
            "https://[2001:db8::1]:8443/file?id=123",
        ),
        ("https://[2001:db8::1]/file", "https://[2001:db8::1]/file"),
        ("https://user:secret@192.0.2.1:8443/file", "https://192.0.2.1:8443/file"),
        ("https://example.org/file?format=csv&key=secret", "https://example.org/file?format=csv"),
    ],
)
def test_diagnostic_urls_are_valid_and_idempotent_for_ipv6_and_other_hosts(url, expected):
    assert public_url(url) == expected
    assert public_url(expected) == expected


def test_observation_callback_records_started_and_finished_steps():
    observations = []
    collect_repository_candidate_with_report(
        URL,
        fetch_html=lambda _: html(BARRIER, 202),
        observe=lambda index, value: observations.append((index, value)),
    )
    assert [o[1]["status"] for o in observations] == ["running", "blocked"]
    assert observations[0][0] == observations[1][0]


def test_page_errors_still_return_controlled_diagnostics():
    def failure(_):
        raise PageFetchError("Internal provider text must not appear in trace")

    result = collect_repository_candidate_with_report(URL, fetch_html=failure)
    assert result.report.method_attempts[0]["code"] == "repository_unavailable"
    assert "Internal provider" not in str(result.report.method_attempts)
