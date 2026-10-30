"""Fixture-backed multi-request API collection; no live services or model calls."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from collector.budget import CollectionBudgetExceeded, collection_budget
from collector.classification.page import PageClassification
from collector.collection.connectors.dryad import DryadConnector
from collector.collection.connectors.dspace import DSpaceConnector
from collector.collection.connectors.inveniordm import InvenioRDMConnector
from collector.collection.connectors.metadata import MetadataReader, api_link
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.collection.http import JsonResponse
from collector.collection.registry import ConnectorRegistry, default_registry
from collector.collection.service import collect_repository_candidate_with_report
from collector.config import DEFAULT_CONFIG, configured_repository_connectors
from collector.network.fetch import FetchedPage
from collector.storage.models import DistributionCandidate, ValidationResult

ITEM = "11111111-1111-4111-8111-111111111111"
BUNDLE = "22222222-2222-4222-8222-222222222222"
FILE = "33333333-3333-4333-8333-333333333333"
THUMBNAIL = "44444444-4444-4444-8444-444444444444"


def link(url):
    return {"href": url}


@pytest.fixture
def cases():
    dryad_url = "https://datadryad.org/stash/dataset/doi:10.5061/dryad.fixture"
    dryad_api = "https://datadryad.org/api/v2/datasets/doi%3A10.5061%2Fdryad.fixture"
    version_api = "https://datadryad.org/api/v2/versions/123"
    dryad_file = "https://datadryad.org/api/v2/files/456"
    dataset = {
        "identifier": "doi:10.5061/dryad.fixture",
        "visibility": "public",
        "publicationDate": "2024-01-01",
        "license": "CC0",
        "_links": {"stash:version": link(version_api)},
    }
    version = {
        "title": "Health survey",
        "abstract": "Disease surveillance measurements.",
        "versionNumber": 1,
        "_links": {
            "self": link(version_api),
            "stash:dataset": link(dryad_api),
            "stash:files": link(version_api + "/files"),
        },
    }
    dryad_files = [
        {
            "path": "survey.csv",
            "size": 1000,
            "mimeType": "text/csv",
            "_links": {
                "self": link(dryad_file),
                "stash:version": link(version_api),
                "stash:download": link(dryad_file + "/download"),
            },
        }
    ]

    invenio_url = "https://rdm.example.org/records/abc12-def34"
    invenio_api = "https://rdm.example.org/api/records/abc12-def34"
    record = {
        "id": "abc12-def34",
        "is_published": True,
        "access": {"files": "public"},
        "metadata": {
            "title": "Health survey",
            "description": "Disease surveillance.",
            "publication_date": "2024-01-01",
            "rights": [{"id": "cc-by-4.0"}],
        },
        "pids": {"doi": {"identifier": "10.1234/health.v1"}},
        "versions": {"index": 1},
        # Embedded summaries are not enough to validate transfer status.
        "files": {"enabled": True, "entries": {"survey.csv": {"key": "survey.csv"}}},
    }
    invenio_files = {
        "enabled": True,
        "entries": [
            {
                "key": "survey.csv",
                "status": "completed",
                "mimetype": "text/csv",
                "size": 1000,
                "links": {"content": invenio_api + "/files/survey.csv/content"},
            }
        ],
    }

    dspace_url = "https://repo.example.org/items/" + ITEM
    root = "https://api.example.org/server/api"
    dspace_api = root + "/core/items/" + ITEM
    item = {
        "uuid": ITEM,
        "type": "item",
        "inArchive": True,
        "withdrawn": False,
        "metadata": {
            "dc.title": [{"value": "Health survey"}],
            "dc.description.abstract": [{"value": "Disease surveillance."}],
            "dc.identifier.doi": [{"value": "10.1234/survey"}],
        },
        "_links": {"bundles": link(dspace_api + "/bundles")},
    }
    bundles = {
        "_embedded": {
            "bundles": [
                {
                    "uuid": BUNDLE,
                    "name": "ORIGINAL",
                    "_links": {
                        "bitstreams": link(root + "/core/bundles/" + BUNDLE + "/bitstreams")
                    },
                },
                {"uuid": THUMBNAIL, "name": "THUMBNAIL", "_links": {}},
            ]
        },
        "page": {"totalElements": 2},
    }
    bitstreams = {
        "_embedded": {
            "bitstreams": [
                {
                    "uuid": FILE,
                    "name": "survey.csv",
                    "type": "bitstream",
                    "sizeBytes": 1000,
                    "_links": {"content": link(root + "/core/bitstreams/" + FILE + "/content")},
                }
            ]
        },
        "page": {"totalElements": 1},
    }
    return {
        "dryad": (
            DryadConnector(),
            dryad_url,
            dryad_api,
            {
                dryad_api: dataset,
                version_api: version,
                version_api + "/files": {"_embedded": {"stash:files": dryad_files}, "total": 1},
            },
        ),
        "inveniordm": (
            InvenioRDMConnector(("rdm.example.org",)),
            invenio_url,
            invenio_api,
            {
                invenio_api: record,
                invenio_api + "/files": invenio_files,
            },
        ),
        "dspace": (
            DSpaceConnector((("repo.example.org", root),)),
            dspace_url,
            dspace_api,
            {
                dspace_api: item,
                dspace_api + "/bundles": bundles,
                root + "/core/bundles/" + BUNDLE + "/bitstreams": bitstreams,
            },
        ),
    }


def transport(mapping, calls):
    def fetch(url):
        calls.append(url)
        assert url in mapping, f"Unexpected metadata request: {url}"
        return JsonResponse(url, url, 200, "application/json", copy.deepcopy(mapping[url]))

    return fetch


@pytest.mark.parametrize("kind,expected_requests", [("dryad", 3), ("inveniordm", 2), ("dspace", 3)])
def test_full_api_collection_preserves_identity_and_checks_data(cases, kind, expected_requests):
    connector, url, api, mapping = cases[kind]
    calls, checked = [], []

    class Accept:
        def classify(self, page, resources):
            assert page.title == "Health survey"
            assert len(resources) == 1
            return PageClassification(True)

    def validate(resource):
        checked.append(resource)
        return ValidationResult(resource.url, resource.url, "CSV", True, 206)

    result = collect_repository_candidate_with_report(
        url,
        registry=ConnectorRegistry([connector]),
        fetch_json=transport(mapping, calls),
        fetch_html=lambda _: pytest.fail("Successful API must avoid HTML fallback"),
        classifier=Accept(),
        validate=validate,
    )
    assert len(calls) == expected_requests and len(checked) == 1
    dataset = result.datasets[0]
    assert dataset.hosting_platform == kind and dataset.dataset_url == url
    assert dataset.record_identity["native_id"] == connector.reference_identity(url).native_id
    assert result.report.method_attempts[0]["request_attempts"] == expected_requests
    assert result.report.method_attempts[0]["http_status"] == 200
    assert not result.report.errors


@pytest.mark.parametrize("kind", ["dryad", "inveniordm", "dspace"])
def test_failed_related_request_counts_prior_metadata_attempts(cases, kind):
    connector, url, api, mapping = cases[kind]
    calls = []

    def fetch(metadata_url):
        calls.append(metadata_url)
        if metadata_url == api:
            return JsonResponse(api, api, 200, "application/json", mapping[api], request_attempts=2)
        error = CollectionTransportError(
            "repository_http_error", "fetch", http_status=503, final_url=metadata_url,
        )
        error.request_attempts = 3
        raise error

    result = collect_repository_candidate_with_report(
        url, registry=ConnectorRegistry([connector]), fetch_json=fetch,
        fetch_html=lambda _: FetchedPage(url, url, "<html>No data</html>", 200, "text/html"),
    )
    attempt = result.report.method_attempts[0]
    assert len(calls) == 2
    assert attempt["request_attempts"] == 5
    assert attempt["http_status"] == 503
    assert attempt["code"] == "repository_http_error"


@pytest.mark.parametrize("kind", ["dryad", "inveniordm", "dspace"])
def test_metadata_identity_mismatch_fails_before_file_reads(cases, kind):
    connector, url, api, mapping = cases[kind]
    if kind == "dryad":
        mapping[api]["identifier"] = "doi:10.5061/dryad.other"
    elif kind == "inveniordm":
        mapping[api]["id"] = "other-record"
    else:
        mapping[api]["uuid"] = FILE
    calls = []
    with pytest.raises(ValueError):
        connector.fetch_metadata(url, transport(mapping, calls))
    assert calls == [api]
    result = collect_repository_candidate_with_report(
        url, registry=ConnectorRegistry([connector]), fetch_json=transport(mapping, []),
        fetch_html=lambda _: FetchedPage(url, url, "<html>No data</html>", 200, "text/html"),
    )
    attempt = result.report.method_attempts[0]
    assert attempt["code"] == "repository_metadata_invalid"
    assert attempt["failure_phase"] == "normalize" and attempt["http_status"] == 200
    assert attempt["request_attempts"] == 1


@pytest.mark.parametrize("kind", ["dryad", "inveniordm", "dspace"])
def test_no_unknown_html_links_are_collected_without_api_evidence(cases, kind):
    connector, url, _, _ = cases[kind]
    links = [DistributionCandidate("https://elsewhere.example/data.csv", "CSV", 1)]
    assert connector.scope_resources(url, links) == []


def test_dryad_files_cannot_belong_to_another_version(cases):
    connector, url, _, mapping = cases["dryad"]
    payload = connector.fetch_metadata(url, transport(mapping, [])).payload
    payload["files"][0]["_links"]["stash:version"] = link("/api/v2/versions/999")
    with pytest.raises(ValueError, match="version mismatch"):
        connector.normalize(url, payload)


def test_invenio_disabled_files_do_not_trigger_a_file_request(cases):
    connector, url, api, mapping = cases["inveniordm"]
    mapping[api]["files"] = {"enabled": False}
    calls = []
    response = connector.fetch_metadata(url, transport(mapping, calls))
    assert connector.normalize(url, response.payload).resources == () and calls == [api]


def test_invenio_hidden_files_keep_restricted_access(cases):
    connector, url, api, mapping = cases["inveniordm"]
    mapping[api + "/files"]["entries"][0]["access"] = {"hidden": True}
    response = connector.fetch_metadata(url, transport(mapping, []))
    assert connector.normalize(url, response.payload).resources[0].signals["restricted"] is True


def test_pdf_mime_is_excluded_even_without_filename_extension(cases):
    connector, url, api, mapping = cases["inveniordm"]
    file = mapping[api + "/files"]["entries"][0]
    file.update(key="paper", mimetype="application/pdf")
    file["links"]["content"] = api + "/files/paper/content"
    result = collect_repository_candidate_with_report(
        url, registry=ConnectorRegistry([connector]), fetch_json=transport(mapping, []),
        fetch_html=lambda _: pytest.fail("PDF listing must not require HTML"),
        validate=lambda _: pytest.fail("PDF content must not be downloaded"),
    )
    assert not result.datasets and result.report.verification_complete


@pytest.mark.parametrize("change", ["draft", "file_scope", "duplicate", "not_completed"])
def test_invenio_rejects_drafts_and_ambiguous_files(cases, change):
    connector, url, api, mapping = cases["inveniordm"]
    if change == "draft":
        mapping[api]["is_published"] = False
        with pytest.raises(ValueError):
            connector.fetch_metadata(url, transport(mapping, []))
        return
    entries = mapping[api + "/files"]["entries"]
    if change == "file_scope":
        entries[0]["links"]["content"] = "/api/records/other/files/survey.csv/content"
    elif change == "duplicate":
        entries.append(copy.deepcopy(entries[0]))
    else:
        entries[0]["status"] = "pending"
    response = connector.fetch_metadata(url, transport(mapping, []))
    with pytest.raises(ValueError):
        connector.normalize(url, response.payload)


@pytest.mark.parametrize("flag", ["withdrawn", "inArchive"])
def test_dspace_rejects_withdrawn_or_unpublished_items(cases, flag):
    connector, url, api, mapping = cases["dspace"]
    mapping[api][flag] = flag == "withdrawn"
    with pytest.raises(ValueError):
        connector.fetch_metadata(url, transport(mapping, []))


def test_dspace_only_original_bundle_is_read(cases):
    connector, url, _, mapping = cases["dspace"]
    calls = []
    connector.fetch_metadata(url, transport(mapping, calls))
    assert not any(THUMBNAIL in request for request in calls)


@pytest.mark.parametrize("kind", ["dryad", "inveniordm", "dspace"])
def test_pdf_only_record_never_calls_models_or_download_validation(cases, kind):
    connector, url, api, mapping = cases[kind]
    if kind == "dryad":
        file = mapping["https://datadryad.org/api/v2/versions/123/files"]["_embedded"][
            "stash:files"
        ][0]
        file["path"], file["mimeType"] = "paper.pdf", "application/pdf"
    elif kind == "inveniordm":
        file = mapping[api + "/files"]["entries"][0]
        file["key"], file["mimetype"] = "paper.pdf", "application/pdf"
        file["links"]["content"] = api + "/files/paper.pdf/content"
    else:
        file = next(v for k, v in mapping.items() if "/bitstreams" in k)["_embedded"]["bitstreams"][
            0
        ]
        file["name"] = "paper.pdf"

    class NoModel:
        def classify(self, *args):
            pytest.fail("A PDF publication cannot trigger dataset acceptance")

    result = collect_repository_candidate_with_report(
        url,
        registry=ConnectorRegistry([connector]),
        fetch_json=transport(mapping, []),
        fetch_html=lambda _: pytest.fail("PDF-only listing is authoritative"),
        classifier=NoModel(),
        validate=lambda _: pytest.fail("No data file to validate"),
    )
    assert not result.datasets and result.report.verification_complete


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/api/records/1",
        "https://127.0.0.1/api/records/1",
        "https://user:secret@repo.example/api/records/1",
        "/outside/records/1",
        "/api/%2e%2e/private",
        "javascript:alert(1)",
        "",
        123,
    ],
)
def test_related_metadata_links_cannot_escape_api(target):
    with pytest.raises(ValueError):
        api_link("https://repo.example/api", target)


def test_paginated_listing_follows_only_same_resource_and_retains_all_entries():
    url = "https://repo.example/api/files"
    mapping = {
        url: {
            "_embedded": {"files": [{"id": 1}]},
            "total": 2,
            "_links": {"next": link(url + "?page=2")},
        },
        url + "?page=2": {"_embedded": {"files": [{"id": 2}]}, "total": 2},
    }
    reader = MetadataReader("https://repo.example/api", transport(mapping, []))
    assert reader.listing(url, "files") == [{"id": 1}, {"id": 2}]
    assert reader.attempts == 2


@pytest.mark.parametrize("change", ["missing", "truncated", "changed_scope", "loop"])
def test_missing_or_incomplete_listing_is_not_authoritative_empty(change):
    url = "https://repo.example/api/files"
    p = {"_embedded": {"files": []}, "total": 0}
    if change == "missing":
        p = {}
    elif change == "truncated":
        p["total"] = 2
    else:
        p["_links"] = {"next": link(url if change == "loop" else "/api/other")}
    reader = MetadataReader("https://repo.example/api", transport({url: p}, []))
    with pytest.raises(ValueError):
        reader.listing(url, "files")


def test_pagination_and_request_counts_are_bounded():
    def fetch(url):
        number = int(url.rsplit("=", 1)[-1])
        p = {"_embedded": {"files": []}, "_links": {"next": link(f"/api/files?page={number + 1}")}}
        return JsonResponse(url, url, 200, "application/json", p)

    reader = MetadataReader("https://repo.example/api", fetch)
    with pytest.raises(CollectionResponseError):
        reader.listing("https://repo.example/api/files?page=1", "files")
    assert reader.requests == 5


def test_expired_budget_prevents_related_metadata_request():
    reader = MetadataReader("https://repo.example/api", lambda _: pytest.fail("network"))
    with collection_budget(seconds=-1), pytest.raises(CollectionBudgetExceeded):
        reader.read("https://repo.example/api/records/1")


def test_default_registry_selects_all_proposed_instances():
    registry = default_registry(DEFAULT_CONFIG)
    for host in DEFAULT_CONFIG.inveniordm_hosts:
        assert registry.select(f"https://{host}/records/abc12-def34").connector.name == "inveniordm"
    for host, root in DEFAULT_CONFIG.dspace_api_bases:
        assert (
            registry.select(f"https://{host}/items/{ITEM}").api_url == root + "/core/items/" + ITEM
        )
    assert registry.select("https://unknown.example/records/abc12-def34") is None
    assert registry.select("https://unknown.example/items/" + ITEM) is None


def test_repository_connector_configuration_overrides_defaults(monkeypatch):
    monkeypatch.setenv("COLLECTION_INVENIORDM_HOSTS", "rdm.example.org")
    monkeypatch.setenv(
        "COLLECTION_DSPACE_API_BASES", '{"repo.example.org":"https://api.example.org/server/api"}'
    )
    config = replace(DEFAULT_CONFIG, **configured_repository_connectors())
    registry = default_registry(config)
    assert registry.select("https://rdm.example.org/records/abc12-def34") is not None
    assert registry.select("https://repository.cern/records/abc12-def34") is None
    assert registry.select("https://repo.example.org/items/" + ITEM) is not None
