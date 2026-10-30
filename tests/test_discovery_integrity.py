"""Discovery contract regressions with local documents and simulated paginated data."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pytest

from collector.budget import CollectionBudgetExceeded
from collector.classification.page import PageClassification
from collector.collection.service import analyze_discovered_page, collect_source_with_report
from collector.discovery.adapters import CKANAdapter, DataJsonAdapter, SocrataAdapter
from collector.discovery.adapters.shared import JsonDocument, fetch_json_url
from collector.storage.models import ValidationResult


class Accept:
    def classify(self, *args):
        return PageClassification(True)


class Response(io.BytesIO):
    def __init__(self, body: bytes, final_url: str):
        super().__init__(body)
        self.final_url = final_url

    def geturl(self):
        return self.final_url


def catalog(*, landing="datasets/health", download="files/health.csv"):
    return {
        "dataset": [{
            "identifier": "health",
            "title": "Health survey",
            "landingPage": landing,
            "issued": "2024-01-01",
            "license": "CC-BY-4.0",
            "distribution": [{"downloadURL": download, "format": "CSV"}],
        }],
    }


@pytest.mark.parametrize("record_type", [
    "Dataset",
    "dcat:Dataset",
    "http://www.w3.org/ns/dcat#Dataset",
    "https://www.w3.org/ns/dcat#Dataset",
    "https://schema.org/Dataset",
    ["foaf:Document", "http://www.w3.org/ns/dcat#Dataset"],
])
@pytest.mark.parametrize("iri_object", [False, True])
def test_dcat_recognizes_supported_types_and_iri_objects(record_type, iri_object):
    def iri(value):
        return {"@id": value} if iri_object else value

    data = {
        "@graph": [{
            "@type": record_type,
            "dct:title": "Health survey",
            "dcat:landingPage": iri("datasets/health"),
            "dcat:distribution": {
                "dcat:downloadURL": [iri("files/health.csv")],
                "dct:format": "CSV",
            },
        }],
    }
    adapter = DataJsonAdapter(fetch_json=lambda _: data)
    source = "https://catalog.example/catalog/data.json"
    assert adapter.detect(source)
    page, = adapter.discover(source)
    assert page.url == "https://catalog.example/catalog/datasets/health"
    resource, = page.distributions
    assert resource.url == "https://catalog.example/catalog/files/health.csv"
    assert resource.format == "CSV" and resource.same_domain


@pytest.mark.parametrize("record_type", [
    "foaf:Dataset", "https://unrelated.example/types/Dataset", "dataset",
])
def test_dcat_does_not_match_unrelated_types_by_local_name(record_type):
    adapter = DataJsonAdapter(fetch_json=lambda _: {"@graph": [{"@type": record_type}]})
    assert not adapter.detect("https://catalog.example")


def test_data_json_retains_legacy_literal_url_objects():
    data = catalog(
        landing={"@value": "datasets/health"},
        download={"value": "files/health.csv"},
    )
    page, = DataJsonAdapter(fetch_json=lambda _: data).discover("https://catalog.example")
    assert page.url == "https://catalog.example/datasets/health"
    assert page.distributions[0].url == "https://catalog.example/files/health.csv"


@pytest.mark.parametrize("source,expected_catalog,expected_base", [
    (
        "https://catalog.example/catalog/search?q=health",
        "https://catalog.example/data.json",
        "https://catalog.example/",
    ),
    (
        "https://catalog.example/catalog/data.json",
        "https://catalog.example/catalog/data.json",
        "https://catalog.example/catalog/",
    ),
])
def test_data_json_relative_urls_use_catalog_document(source, expected_catalog, expected_base):
    calls = []

    def fetch(url):
        calls.append(url)
        return catalog()

    page, = DataJsonAdapter(fetch_json=fetch).discover(source)
    assert calls == [expected_catalog]
    assert page.url == expected_base + "datasets/health"
    assert page.distributions[0].url == expected_base + "files/health.csv"
    assert page.distributions[0].same_domain
    assert page.metadata_source_url == expected_catalog


def test_redirected_catalog_sets_effective_base_and_metadata_evidence(monkeypatch):
    final_url = "https://cdn.example/catalog/v2/data.json"
    response = Response(json.dumps(catalog()).encode(), final_url)
    monkeypatch.setattr(
        "collector.discovery.adapters.shared.open_public_http_url",
        lambda *args, **kwargs: response,
    )
    page, = DataJsonAdapter().discover("https://catalog.example/catalog/search")
    assert response.closed
    assert page.metadata_source_url == final_url
    assert page.discovery_metadata["data_json_url"] == final_url
    assert page.url == "https://cdn.example/catalog/v2/datasets/health"
    assert page.distributions[0].url == "https://cdn.example/catalog/v2/files/health.csv"
    dataset = analyze_discovered_page(page, classifier=Accept())
    for evidence in dataset.metadata_provenance.values():
        assert evidence[0]["source_url"] == final_url


@pytest.mark.parametrize("kind", ["ckan", "socrata", "data_json"])
@pytest.mark.parametrize("redirected", [False, True])
def test_all_structured_adapters_preserve_actual_metadata_source(kind, redirected):
    payloads = {
        "ckan": {"success": True, "result": {"results": [{
            "name": "health", "title": "Health", "license_title": "CC-BY-4.0",
            "resources": [{"url": "https://files.example/health.csv", "format": "CSV"}],
        }]}},
        "socrata": {"results": [{
            "resource": {"id": "abcd-1234", "name": "Health", "type": "dataset",
                         "license": "CC-BY-4.0"},
            "metadata": {"domain": "catalog.example"},
        }]},
        "data_json": catalog(),
    }
    calls = []
    final_url = "https://api.example/metadata?record=health"

    def fetch(url):
        calls.append(url)
        payload = payloads[kind]
        return JsonDocument(payload, final_url) if redirected else payload

    adapter = {"ckan": CKANAdapter, "socrata": SocrataAdapter,
               "data_json": DataJsonAdapter}[kind](fetch_json=fetch)
    page, = adapter.discover("https://catalog.example")
    expected_source = final_url if redirected else calls[0]
    assert page.metadata_source_url == expected_source
    dataset = analyze_discovered_page(page, classifier=Accept())
    assert dataset.metadata_provenance["sharing_license"] == [{
        "value": "CC-BY-4.0", "kind": "adapter", "source_url": expected_source,
    }]


def socrata_catalog():
    return {"results": [{
        "resource": {"id": "abcd-1234", "name": "Health survey", "type": "dataset",
                     "rows": 2501},
        "metadata": {"domain": "catalog.example"},
    }]}


@pytest.mark.parametrize("encoding", ["CSV", "JSON"])
def test_socrata_pagination_contract_can_retrieve_more_than_one_thousand_rows(encoding):
    page, = SocrataAdapter(fetch_json=lambda _: socrata_catalog()).discover(
        "https://catalog.example"
    )
    resource = next(item for item in page.distributions if item.format == encoding)
    assert resource.signals["api_endpoint"] and resource.signals["paginated"]
    assert resource.signals["complete_export"] is False
    assert "export" not in resource.anchor.lower()
    assert "paginated" in resource.anchor.lower()
    pagination = resource.signals["pagination"]
    parts = urlsplit(resource.url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert query[pagination["limit_parameter"]] == "1000"
    assert query[pagination["offset_parameter"]] == "0"
    assert query[pagination["order_parameter"]] == ":id"

    rows = list(range(2501))
    received, offsets = [], []
    current_url = resource.url
    while True:
        params = parse_qs(urlsplit(current_url).query)
        offset = int(params[pagination["offset_parameter"]][0])
        limit = int(params[pagination["limit_parameter"]][0])
        offsets.append(offset)
        batch = rows[offset:offset + limit]
        if not batch:
            assert pagination["completion"] == "empty_page"
            break
        received.extend(batch)
        query[pagination["offset_parameter"]] = str(
            offset + pagination["next_offset_increment"]
        )
        current_url = urlunsplit(parts._replace(query=urlencode(query)))

    assert offsets == [0, 1000, 2000, 3000]
    assert received == rows
    assert len(page.distributions) == 2


def test_socrata_pagination_signals_survive_bounded_collection():
    adapter = SocrataAdapter(fetch_json=lambda _: socrata_catalog())
    result = collect_source_with_report(
        "https://catalog.example", discover=adapter.discover, classifier=Accept(),
        validate=lambda item: ValidationResult(item.url, item.url, item.format, True, 200),
        fetch_html=lambda _: pytest.fail("Structured metadata needs no HTML request"),
    )
    dataset, = result.datasets
    resource, = dataset.distributions
    assert resource.signals["pagination"]["offset_parameter"] == "$offset"
    assert resource.signals["complete_export"] is False


@pytest.mark.parametrize("body", [
    b'{"title":"\xff"}',
    b'{"missing":}',
    b'{"nested":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
])
def test_malformed_or_deep_json_is_controlled_and_closes_response(monkeypatch, body):
    response = Response(body, "https://catalog.example/data.json")
    monkeypatch.setattr(
        "collector.discovery.adapters.shared.open_public_http_url",
        lambda *args, **kwargs: response,
    )
    with pytest.raises(ValueError):
        fetch_json_url("https://catalog.example/data.json")
    assert response.closed


@pytest.mark.parametrize("exhausted", [False, True])
def test_discovery_http_errors_close_even_when_budget_expires(monkeypatch, exhausted):
    body = io.BytesIO(b"private provider diagnostic")
    error = HTTPError("https://catalog.example/data.json", 503, "Unavailable", {}, body)

    def fail(*args, **kwargs):
        raise error

    def budget():
        if exhausted:
            raise CollectionBudgetExceeded()

    monkeypatch.setattr("collector.discovery.adapters.shared.open_public_http_url", fail)
    monkeypatch.setattr("collector.discovery.adapters.shared.check_collection_budget", budget)
    with pytest.raises(CollectionBudgetExceeded if exhausted else ValueError):
        fetch_json_url("https://catalog.example/data.json")
    assert body.closed
