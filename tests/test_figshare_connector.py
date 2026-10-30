from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from collector.classification.page import PageClassification
from collector.collection.connectors.figshare import FigshareConnector
from collector.collection.http import JsonResponse
from collector.collection.registry import default_registry
from collector.collection.service import collect_repository_candidate_with_report
from collector.config import DEFAULT_CONFIG
from collector.network.fetch import FetchedPage
from collector.storage.models import DistributionCandidate, ValidationResult

URL = "https://springernature.figshare.com/articles/dataset/BCG_data/20522745/1"
API = "https://api.figshare.com/v2/articles/20522745/versions/1"
FILE = "https://ndownloader.figshare.com/files/36733443"


@pytest.fixture
def record():
    path = Path(__file__).parent / "fixtures/connectors/figshare_record.json"
    return json.loads(path.read_text())


@pytest.mark.parametrize("path,suffix", [
    ("/articles/dataset/BCG_data/20522745/1", "/20522745/versions/1"),
    ("/articles/dataset/BCG_data/20522745", "/20522745"),
    ("/articles/20522745/1/", "/20522745/versions/1"),
    ("/articles/20522745", "/20522745"),
])
def test_registry_resolves_exact_article_and_requested_version(path, suffix):
    selected = default_registry(DEFAULT_CONFIG).select("https://figshare.com" + path)
    assert selected.connector.name == "figshare"
    assert selected.api_url == "https://api.figshare.com/v2/articles" + suffix


@pytest.mark.parametrize("url", [
    "http://figshare.com/articles/20522745",
    "https://figshare.com.evil.test/articles/20522745",
    "https://unknown.figshare.com/articles/20522745",
    "https://user:secret@figshare.com/articles/20522745",
    "https://figshare.com:8443/articles/20522745",
    "https://figshare.com/articles/0",
    "https://figshare.com/articles/20522745/0",
    "https://figshare.com/articles/20522745/1?version=2",
    "https://figshare.com/collections/title/20522745",
    "https://ndownloader.figshare.com/files/36733443",
])
def test_unsupported_or_ambiguous_references_are_not_resolved(url):
    assert not FigshareConnector().supports(url)


def test_configured_hosts_remain_explicit():
    config = replace(DEFAULT_CONFIG, figshare_hosts=("institution.figshare.com",))
    registry = default_registry(config)
    assert registry.select("https://institution.figshare.com/articles/20522745") is not None
    assert registry.select(URL) is None


def test_collection_uses_public_api_without_html_barrier(record):
    class Accept:
        def classify(self, page, resources):
            assert page.title == record["title"]
            assert resources[0].url == FILE
            return PageClassification(True)

    def fetch(url):
        assert url == API
        return JsonResponse(url, url, 200, "application/json", record)

    def validate(resource):
        assert resource.anchor == "12864_2022_8826_MOESM1_ESM.zip"
        return ValidationResult(resource.url, resource.url, "ZIP", True, 206)

    result = collect_repository_candidate_with_report(
        URL, fetch_json=fetch, classifier=Accept(), validate=validate,
        fetch_html=lambda _: pytest.fail("API success must avoid blocked HTML"),
    )
    dataset = result.datasets[0]
    assert dataset.dataset_url == URL
    assert dataset.description == "Tables of SNPs and indels compared to M. tuberculosis."
    assert dataset.doi == record["doi"]
    assert dataset.sharing_license == "CC BY + CC0"
    assert dataset.hosting_platform == "figshare"
    assert dataset.record_identity["version"] == "1"
    assert dataset.record_identity["native_id"] == "20522745"
    assert dataset.discovery_method == "figshare_api"
    assert result.report.method_attempts[0]["http_status"] == 200
    assert result.report.method_attempts[0]["checks"][0]["http_status"] == 206
    assert not result.report.errors


@pytest.mark.parametrize("change", [
    "wrong_id", "wrong_version", "missing_version", "missing_title", "missing_files",
    "invalid_file", "duplicate_file", "missing_download",
])
def test_malformed_metadata_cannot_be_treated_as_success(record, change):
    if change == "wrong_id":
        record["id"] = 456
    elif change == "wrong_version":
        record["version"] = 2
    elif change == "missing_version":
        del record["version"]
    elif change == "missing_title":
        del record["title"]
    elif change == "missing_files":
        del record["files"]
    elif change == "invalid_file":
        record["files"] = [None]
    elif change == "duplicate_file":
        record["files"].append(copy.deepcopy(record["files"][0]))
    else:
        del record["files"][0]["download_url"]
    with pytest.raises(ValueError):
        FigshareConnector().normalize(URL, record)


def test_unversioned_reference_preserves_actual_response_version(record):
    record["version"] = 2
    record["doi"] = "10.6084/m9.figshare.20522745.v2"
    resolved = FigshareConnector().normalize(URL.rsplit("/", 1)[0], record)
    assert resolved.identity.version == "2"
    assert resolved.doi.endswith(".v2")


def test_embargo_metadata_is_preserved_without_claiming_open_access(record):
    record["is_embargoed"] = True
    resolved = FigshareConnector().normalize(URL, record)
    assert resolved.resources[0].signals["restricted"] is True


def test_fallback_does_not_widen_pinned_version(record):
    connector = FigshareConnector()
    links = [DistributionCandidate(FILE, "ZIP", 1),
             DistributionCandidate("https://ndownloader.figshare.com/files/999", "ZIP", 1)]
    assert connector.scope_resources(URL, links) == []
    assert connector.scope_resources(URL, links, connector.normalize(URL, record)) == links[:1]
    assert connector.reference_identity(URL).version == "1"


def test_authoritative_empty_listing_stops_without_html(record):
    record["files"] = []
    result = collect_repository_candidate_with_report(
        URL, fetch_json=lambda _: record,
        fetch_html=lambda _: pytest.fail("Empty authoritative listing must stop"),
    )
    assert not result.datasets and result.report.verification_complete


def test_wrong_version_cannot_collect_newer_html_file(record):
    record["version"] = 2
    html = f'<html><title>BCG data</title><a href="{FILE}">data.zip</a></html>'
    result = collect_repository_candidate_with_report(
        URL, fetch_json=lambda _: record,
        fetch_html=lambda _: FetchedPage(URL, URL, html, 200, "text/html"),
        validate=lambda _: pytest.fail("Wrong version must not be collected"),
    )
    assert not result.datasets
    assert result.report.method_attempts[0]["code"] == "repository_metadata_invalid"
