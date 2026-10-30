from __future__ import annotations

import copy
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from collector.budget import collection_budget
from collector.classification.page import PageClassification
from collector.collection.browser import BrowserSession
from collector.collection.connectors.dataverse import DataverseConnector
from collector.collection.connectors.zenodo import ZenodoConnector
from collector.collection.registry import ConnectorRegistry, default_registry
from collector.collection.service import collect_repository_candidate_with_report
from collector.config import DEFAULT_CONFIG
from collector.discovery.adapters.shared import fetch_json_url
from collector.network.fetch import FetchedPage
from collector.storage.metadata import enrich_from_repository
from collector.storage.models import ValidationResult

ZENODO = "https://zenodo.org/records/123"
DATAVERSE = "https://dataverse.harvard.edu/file.xhtml?fileId=123"
FIXTURES = Path(__file__).parent / "fixtures" / "connectors"


@pytest.fixture
def zenodo():
    return json.loads((FIXTURES / "zenodo_record.json").read_text())


@pytest.fixture
def dataverse_file():
    return json.loads((FIXTURES / "dataverse_file.json").read_text())


class Accept:
    def classify(self, page, distributions):
        return PageClassification(True)


def available(resource):
    return ValidationResult(resource.url, resource.url, resource.format, True, 206)


def collect(url, payload, **kwargs):
    return collect_repository_candidate_with_report(
        url, fetch_json=lambda _: payload,
        fetch_html=lambda _: pytest.fail("API resolution should be sufficient"),
        classifier=Accept(), validate=available, **kwargs,
    )


@pytest.mark.parametrize("url", [
    "http://zenodo.org/records/123", "https://zenodo.org.evil.test/records/123",
    "https://user:secret@zenodo.org/records/123", "https://zenodo.org:8443/records/123",
    "https://zenodo.org/records/0", "https://zenodo.org/communities/123",
    "https://zenodo.org/records/123?version=2", "https://zenodo.org/api/records/123",
    "https://dataverse.harvard.edu:bad/file.xhtml?fileId=123",
    "https://user:secret@dataverse.harvard.edu/file.xhtml?fileId=123",
    "https://dataverse.harvard.edu/file.xhtml?fileId=123&fileId=456",
])
def test_registry_does_not_resolve_unsupported_or_ambiguous_urls(url):
    assert default_registry(DEFAULT_CONFIG).select(url) is None


@pytest.mark.parametrize("path", ["/record/123", "/records/123", "/records/123/"])
def test_zenodo_record_urls_use_the_exact_record_endpoint(path):
    selected = default_registry(DEFAULT_CONFIG).select("https://zenodo.org" + path)
    assert selected.connector.name == "zenodo"
    assert selected.api_url == "https://zenodo.org/api/records/123"


def test_zenodo_concept_doi_resolves_its_verified_version_and_excludes_pdf():
    url = "https://zenodo.org/doi/10.5281/zenodo.15185480"
    payload = json.loads((FIXTURES / "zenodo_transmission_pdf.json").read_text())
    selected = default_registry(DEFAULT_CONFIG).select(url)
    assert selected.api_url == "https://zenodo.org/api/records/15185480"
    record = selected.connector.normalize(url, payload)
    assert record.identity.native_id == "15185481"
    assert record.doi == "10.5281/zenodo.15185481"
    result = collect(url, payload)
    assert not result.datasets
    assert result.report.method_attempts[0]["method"] == "zenodo_api"
    assert result.report.method_attempts[0]["status"] == "empty"
    assert result.report.coverage["checked"] == 0


@pytest.mark.parametrize("field,value", [
    ("conceptrecid", "999"), ("conceptdoi", "10.5281/zenodo.999"),
])
def test_zenodo_concept_doi_rejects_unrelated_version(field, value):
    payload = json.loads((FIXTURES / "zenodo_transmission_pdf.json").read_text())
    payload[field] = value
    with pytest.raises(ValueError, match="identity mismatch"):
        ZenodoConnector().normalize("https://zenodo.org/doi/10.5281/zenodo.15185480", payload)


def test_zenodo_version_doi_cannot_select_another_version(zenodo):
    record = ZenodoConnector().normalize("https://zenodo.org/doi/10.5281/zenodo.123", zenodo)
    assert record.identity.native_id == "123"
    zenodo["id"] = 124
    with pytest.raises(ValueError, match="identity mismatch"):
        ZenodoConnector().normalize("https://zenodo.org/doi/10.5281/zenodo.123", zenodo)


def test_hosts_are_configuration_and_do_not_require_new_connectors():
    config = replace(DEFAULT_CONFIG, dataverse_hosts=("data.example.org",), zenodo_hosts=())
    registry = default_registry(config)
    assert registry.select("https://data.example.org/file.xhtml?fileId=123") is not None
    assert registry.select(DATAVERSE) is None
    assert registry.select(ZENODO) is None


def test_duplicate_connector_names_are_rejected():
    with pytest.raises(ValueError):
        ConnectorRegistry((ZenodoConnector(), ZenodoConnector()))


def test_unc_study31_uses_api_and_collects_data_archive_without_html():
    url = "https://dataverse.unc.edu/dataset.xhtml?persistentId=doi:10.15139/S3/XQW69I"
    payload = json.loads((FIXTURES / "dataverse_unc_study31.json").read_text())
    selected = default_registry(DEFAULT_CONFIG).select(url)
    assert selected.connector.name == "dataverse"
    assert selected.api_url == (
        "https://dataverse.unc.edu/api/v1/datasets/:persistentId/"
        "?persistentId=doi%3A10.15139%2FS3%2FXQW69I"
    )
    requested, checked = [], []

    def fetch_json(api_url):
        requested.append(api_url)
        return payload

    def validate(resource):
        checked.append(resource.url)
        return available(resource)

    result = collect_repository_candidate_with_report(
        url, fetch_json=fetch_json,
        fetch_html=lambda _: pytest.fail("UNC should resolve through the API"),
        classifier=Accept(), validate=validate,
    )
    assert requested == [selected.api_url]
    assert checked == ["https://dataverse.unc.edu/api/access/datafile/7563340"]
    dataset = result.datasets[0]
    assert dataset.doi == "10.15139/s3/xqw69i"
    assert dataset.discovery_method == "dataverse_api"
    assert dataset.record_identity["version"] == "2.0"
    assert dataset.distributions[0].anchor == "S31_21jul2026.zip"


def test_dataverse_metadata_version_id_is_never_used_as_download_id(dataverse_file):
    result = collect(DATAVERSE, dataverse_file)
    dataset = result.datasets[0]
    assert dataset.distributions[0].url.endswith("/datafile/123")
    assert dataset.record_identity["native_id"] == "123"
    assert dataset.record_identity["kind"] == "file"
    assert dataset.doi == "10.7910/dvn/health/survey"


def test_dataverse_unwrapped_single_file_metadata_is_supported(dataverse_file):
    record = DataverseConnector(DEFAULT_CONFIG.dataverse_hosts).normalize(
        DATAVERSE, [dataverse_file["data"]],
    )
    assert record.resources[0].url.endswith("/123")


@pytest.mark.parametrize("data", [[], [{}, {}], {"id": 9000, "label": "survey.csv"}])
def test_dataverse_missing_or_ambiguous_file_identity_is_not_guessed(data):
    with pytest.raises(ValueError):
        DataverseConnector(DEFAULT_CONFIG.dataverse_hosts).normalize(
            DATAVERSE, {"status": "OK", "data": data},
        )


def test_dataverse_mismatched_file_response_is_rejected(dataverse_file):
    dataverse_file["data"]["dataFile"]["id"] = 456
    with pytest.raises(ValueError, match="identity mismatch"):
        DataverseConnector(DEFAULT_CONFIG.dataverse_hosts).normalize(DATAVERSE, dataverse_file)


def test_zenodo_metadata_survives_classification_and_collection(zenodo):
    dataset = collect(ZENODO, zenodo).datasets[0]
    assert dataset.title == "Health survey data"
    assert dataset.description == "Health measurements collected in Switzerland."
    assert dataset.doi == "10.5281/zenodo.123"
    assert dataset.sharing_license == "cc-by-4.0"
    assert dataset.hosting_platform == "zenodo"
    assert dataset.record_identity["version"] == "1.2"
    assert dataset.discovery_method == "zenodo_api"
    assert dataset.metadata_provenance["doi"][0]["source_url"] == ZENODO.replace(
        "/records/", "/api/records/",
    )


def test_zenodo_file_resolution_does_not_use_the_parent_doi_or_other_files(zenodo):
    url = ZENODO + "/files/survey.csv?download=1"
    dataset = collect(url, zenodo).datasets[0]
    assert dataset.dataset_url == url
    assert dataset.title == "survey.csv"
    assert dataset.doi == ""
    assert dataset.record_identity["kind"] == "file"
    assert dataset.record_identity["parent_persistent_id"] == "10.5281/zenodo.123"
    assert [item.anchor for item in dataset.distributions] == ["survey.csv"]
    enriched = enrich_from_repository(dataset, {
        "url": url, "doi": zenodo["doi"], "metadata": {},
    })
    assert enriched.doi == ""


def test_zenodo_file_names_are_decoded_without_widening_scope(zenodo):
    zenodo["files"][0]["key"] = "folder/survey data.csv"
    record = ZenodoConnector().normalize(
        ZENODO + "/files/folder%2Fsurvey%20data.csv", zenodo,
    )
    assert len(record.resources) == 1
    assert record.resources[0].anchor == "folder/survey data.csv"


@pytest.mark.parametrize("change", ["wrong_id", "missing_files", "invalid_file", "missing_link"])
def test_malformed_zenodo_responses_are_not_authoritative_empty(zenodo, change):
    if change == "wrong_id":
        zenodo["id"] = 456
    elif change == "missing_files":
        del zenodo["files"]
    elif change == "invalid_file":
        zenodo["files"] = [None]
    else:
        zenodo["files"][0]["links"] = {}
    with pytest.raises(ValueError):
        ZenodoConnector().normalize(ZENODO, zenodo)


def test_zenodo_missing_requested_file_is_not_an_empty_dataset(zenodo):
    with pytest.raises(ValueError, match="missing"):
        ZenodoConnector().normalize(ZENODO + "/files/missing.csv", zenodo)


def test_zenodo_authoritative_empty_listing_stops_without_html(zenodo):
    zenodo["files"] = []
    result = collect(ZENODO, zenodo)
    assert not result.datasets
    assert result.report.verification_complete
    assert result.report.method_attempts[0]["code"] == "no_download_links"


def test_rejection_stops_zenodo_collection_without_fallback(zenodo):
    class Reject:
        def classify(self, *args):
            return PageClassification(False)

    result = collect_repository_candidate_with_report(
        ZENODO, fetch_json=lambda _: zenodo,
        fetch_html=lambda _: pytest.fail("A rejection must not trigger fallback"),
        classifier=Reject(), validate=lambda _: pytest.fail("Rejected resources are not checked"),
    )
    assert not result.datasets
    assert result.report.method_attempts[0]["code"] == "page_rejected"


def test_zenodo_resource_budget_is_shared_with_fallback(zenodo):
    file = copy.deepcopy(zenodo["files"][0])
    zenodo["files"].append({**file, "key": "third.csv", "links": {
        "self": "https://zenodo.org/files/third.csv",
    }})
    checked = []

    def unavailable(resource):
        checked.append(resource.url)
        return ValidationResult(resource.url, resource.url, resource.format, False, 403)

    result = collect_repository_candidate_with_report(
        ZENODO, fetch_json=lambda _: zenodo, classifier=Accept(), validate=unavailable,
        fetch_html=lambda _: pytest.fail("All three resource checks were consumed"),
    )
    assert len(checked) == 3
    assert result.report.coverage["limited"]
    assert not result.report.verification_complete


@pytest.mark.parametrize("url,selected,other", [
    (ZENODO + "/files/survey.csv", ZENODO + "/files/survey.csv", ZENODO + "/files/other.csv"),
    (DATAVERSE, "https://dataverse.harvard.edu/api/access/datafile/123",
     "https://dataverse.harvard.edu/api/access/datafile/456"),
])
def test_file_html_fallback_cannot_collect_other_files_or_parent_identity(url, selected, other):
    checks = []

    def failed(_):
        raise ValueError("API unavailable")

    def validate(resource):
        checks.append(resource.url)
        return available(resource)

    body = (
        '<html><title>Health</title><link rel="canonical" href="/parent">'
        f'<a href="{other}">other.csv</a><a href="{selected}">survey.csv</a></html>'
    )
    result = collect_repository_candidate_with_report(
        url, fetch_json=failed, classifier=Accept(), validate=validate,
        fetch_html=lambda _: FetchedPage(url, url, body, 200, "text/html"),
    )
    assert checks == [selected]
    assert result.datasets[0].dataset_url == url
    assert not result.report.errors


def test_zenodo_browser_metadata_uses_the_selected_connector(zenodo, monkeypatch):
    session = BrowserSession("http://renderer", "test", DEFAULT_CONFIG)
    monkeypatch.setattr(session, "request", lambda *args, **kwargs: {
        "session_id": "test-session", "metadata": zenodo, "http_status": 200,
    })
    resolved = session.render(ZENODO, metadata_url="https://zenodo.org/api/records/123")
    assert resolved.record.identity.platform == "zenodo"
    assert len(resolved.page.distributions) == 2


def test_browser_malformed_optional_metadata_does_not_discard_html(monkeypatch):
    session = BrowserSession("http://renderer", "test", DEFAULT_CONFIG)
    monkeypatch.setattr(session, "request", lambda *args, **kwargs: {
        "session_id": "test-session", "metadata": {}, "http_status": 200,
        "html": "<html>Health</html>", "final_url": ZENODO,
    })
    assert session.render(ZENODO, metadata_url=ZENODO.replace(
        "/records/", "/api/records/",
    )).html == "<html>Health</html>"


def test_collection_can_parse_lists_without_weakening_catalog_fetches(monkeypatch):
    monkeypatch.setattr(
        "collector.discovery.adapters.shared.open_public_http_url",
        lambda *args, **kwargs: io.BytesIO(b"[]"),
    )
    with pytest.raises(ValueError, match="an object"):
        fetch_json_url("https://example.org/catalog")
    assert fetch_json_url("https://example.org/metadata", allow_list=True) == []


def test_expired_collection_never_requests_zenodo_metadata():
    with collection_budget(seconds=-1):
        result = collect_repository_candidate_with_report(
            ZENODO, fetch_json=lambda _: pytest.fail("Deadline expired"),
        )
    assert result.report.errors[0].code == "collection_budget_exhausted"


def test_custom_registry_is_used_by_the_public_collection_entry(zenodo):
    registry = ConnectorRegistry((ZenodoConnector(("data.example.org",)),))
    url = "https://data.example.org/records/123"
    result = collect(url, zenodo, registry=registry)
    assert result.datasets[0].record_identity["repository_origin"] == "https://data.example.org"


def test_pinned_dataverse_html_canonical_cannot_erase_the_requested_version():
    url = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/X&version=1.0"
    selected = default_registry(DEFAULT_CONFIG).select(url)
    assert selected is not None and selected.api_url is None
    body = (
        '<html><title>Health data</title>'
        '<link rel="canonical" href="/dataset.xhtml?persistentId=doi:10.7910/DVN/X">'
        '<a href="/survey.csv">CSV</a></html>'
    )
    result = collect_repository_candidate_with_report(
        url, fetch_json=lambda _: pytest.fail("The default API is not version-pinned"),
        fetch_html=lambda _: FetchedPage(url, url, body, 200, "text/html"),
        classifier=Accept(), validate=available,
    )
    assert "version=1.0" in result.datasets[0].dataset_url
    assert result.datasets[0].record_identity["version"] == "1.0"
    assert result.report.discovery_methods == ("html",)


def test_verified_api_file_scope_can_include_an_external_download_host(zenodo):
    zenodo["files"][0]["links"]["self"] = "https://files.example.org/survey.csv"
    result = collect(ZENODO + "/files/survey.csv", zenodo)
    assert result.datasets[0].distributions[0].url == "https://files.example.org/survey.csv"


def test_html_recovery_retains_successful_api_identity_and_metadata(zenodo):
    calls = []

    def validate(resource):
        calls.append(resource.url)
        if resource.url.endswith("/content"):
            return ValidationResult(resource.url, resource.url, resource.format, False, 404)
        return available(resource)

    body = '<html><title>Health data</title><a href="/survey.csv">CSV</a></html>'
    result = collect_repository_candidate_with_report(
        ZENODO, fetch_json=lambda _: zenodo, classifier=Accept(), validate=validate,
        fetch_html=lambda _: FetchedPage(ZENODO, ZENODO, body, 200, "text/html"),
    )
    dataset = result.datasets[0]
    assert dataset.discovery_method == "html"
    assert dataset.record_identity["native_id"] == "123"
    assert dataset.doi == zenodo["doi"]
    assert len(calls) == 3


def test_file_html_fallback_never_assigns_the_parent_citation_doi():
    url = ZENODO + "/files/survey.csv"
    body = (
        '<html><title>Health survey</title><meta name="citation_doi" '
        'content="10.5281/zenodo.123"><a href="/records/123/files/survey.csv">CSV</a></html>'
    )
    result = collect_repository_candidate_with_report(
        url, classifier=Accept(), validate=available,
        fetch_html=lambda _: FetchedPage(url, url, body, 200, "text/html"),
    )
    dataset = result.datasets[0]
    assert dataset.doi == ""
    assert dataset.record_identity["kind"] == "file"
    assert dataset.record_identity["native_id"] == "123/files/survey.csv"

