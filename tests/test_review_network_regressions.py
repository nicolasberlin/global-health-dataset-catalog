"""Network review regressions using real handlers and in-memory transports."""

from __future__ import annotations

import gzip
import io
import json
import sys
from contextlib import nullcontext
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

from collector.budget import CollectionBudgetExceeded, collection_budget
from collector.classification.llm_client import HTTPJSONLLMClient, LLMProviderConfig
from collector.classification.page import PageClassification, PageClassificationError
from collector.discovery.adapters import DiscoveredPage
from collector.discovery.sitemap import fetch_text_url
from collector.main import collect_source_with_report
from collector.storage.models import DistributionCandidate
from collector.validation.downloads import probe_url

PROVIDER_URL = "https://llm.example/classify"
DATA_URL = "https://data.example/health.csv"


def client(request=None):
    return HTTPJSONLLMClient(
        provider=LLMProviderConfig(
            name="Test provider",
            endpoint_url=PROVIDER_URL,
            api_key_env_var="TEST_KEY",
            model_env_var="TEST_MODEL",
            default_model="test-model",
            request_body_builder=lambda payload, model: {"model": model, **payload},
            response_text_extractor=lambda body: body["text"],
        ),
        api_key="test-key",
        request=request,
    )


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("collector.budget.monotonic", lambda: now[0])
    return now


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("expired", [False, True])
def test_llm_redirect_never_forwards_credentials_and_closes_body(
    monkeypatch, clock, status, expired,
):
    requests = []
    responses = []

    class RedirectingTransport(HTTPSHandler):
        def https_open(self, request):
            requests.append((request.full_url, request.get_method(),
                             request.get_header("Authorization")))
            headers = Message()
            headers["Location"] = "https://other.example/collect-key"
            response = addinfourl(io.BytesIO(b"redirect"), headers, request.full_url, status)
            response.msg = "Redirect"
            responses.append(response)
            if expired:
                clock[0] += 5
            return response

    # Exercise the default client's opener, redirect and HTTP error machinery,
    # replacing only the final HTTPS transport (no sockets/DNS/provider calls).
    monkeypatch.setattr(
        "collector.classification.llm_client.build_opener",
        lambda *handlers: build_opener(RedirectingTransport(), *handlers),
    )
    expected = CollectionBudgetExceeded if expired else PageClassificationError
    with collection_budget(seconds=5), pytest.raises(expected) as caught:
        client().classify_page({})
    assert requests == [(PROVIDER_URL, "POST", "Bearer test-key")]
    assert len(responses) == 1
    assert responses[0].closed
    if not expired:
        assert caught.value.diagnostics[0].code == "llm_configuration_error"
        assert caught.value.diagnostics[0].recovery == "configuration_required"


@pytest.mark.parametrize("status", [400, 401, 429, 503])
def test_llm_http_errors_close_response_without_reading_it(status):
    class UnreadableBody(io.BytesIO):
        def read(self, *args):
            pytest.fail("An HTTP error body must not be drained")

    body = UnreadableBody(b"provider error")

    def request(*args, **kwargs):
        raise HTTPError(PROVIDER_URL, status, "Error", {"Retry-After": "30"}, body)

    with pytest.raises(PageClassificationError) as caught:
        client(request).classify_page({})
    assert body.closed
    assert caught.value.diagnostics[0].retry_at is not None


@pytest.mark.parametrize("stage", ["provider_envelope", "model_output"])
def test_deep_json_is_a_recoverable_invalid_llm_response(stage):
    levels = sys.getrecursionlimit() + 100
    nested_json = "[" * levels + "0" + "]" * levels
    payload = nested_json if stage == "provider_envelope" else json.dumps({"text": nested_json})
    body = io.BytesIO(payload.encode())
    with pytest.raises(PageClassificationError) as caught:
        client(lambda *args, **kwargs: body).classify_page({})
    assert caught.value.diagnostics[0].code == "llm_invalid_response"
    assert caught.value.diagnostics[0].recovery == "manual"
    assert body.closed


@pytest.mark.parametrize("failure", [TimeoutError("slow body"),
                                     URLError("body disconnected"), OSError("reset")])
@pytest.mark.parametrize("budgeted", [False, True])
def test_http_error_body_read_failure_is_unconfirmed_and_closed(
    monkeypatch, failure, budgeted,
):
    class BrokenBody(io.BytesIO):
        def read(self, *args):
            raise failure

        read1 = read

    body = BrokenBody(b"error")

    def request(*args, **kwargs):
        raise HTTPError(DATA_URL, 403, "Forbidden", {}, body)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", request)
    with collection_budget(seconds=5) if budgeted else nullcontext():
        result = probe_url(DATA_URL, "GET", 1, 100)
    assert result.status_code is None
    assert result.error == str(failure)
    assert body.closed


@pytest.mark.parametrize("method,max_bytes", [("HEAD", 0), ("GET", 100)])
@pytest.mark.parametrize("headers", [None, {"Content-Type": "text/html"}])
@pytest.mark.parametrize("budgeted", [False, True])
def test_bodyless_http_error_retains_probe_metadata(
    monkeypatch, method, max_bytes, headers, budgeted,
):
    final_url = "https://data.example/permission"

    def request(*args, **kwargs):
        raise HTTPError(final_url, 403, "Forbidden", headers, None)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", request)
    with collection_budget(seconds=5) if budgeted else nullcontext():
        result = probe_url(DATA_URL, method, 1, max_bytes)
    assert result.url == DATA_URL
    assert result.final_url == final_url
    assert result.status_code == 403
    assert result.headers == ({"content-type": "text/html"} if headers else {})
    assert result.body_sample == b""
    assert result.error == "HTTP Error 403: Forbidden"


def test_http_error_read_timeout_at_deadline_preserves_budget_failure(monkeypatch, clock):
    class SlowBody(io.BytesIO):
        def read1(self, size):
            clock[0] += 5
            raise TimeoutError("read timeout")

    body = SlowBody(b"error")

    def request(*args, **kwargs):
        raise HTTPError(DATA_URL, 403, "Forbidden", {}, body)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", request)
    with collection_budget(seconds=5), pytest.raises(CollectionBudgetExceeded):
        probe_url(DATA_URL, "GET", 10, 100)
    assert body.closed


def test_collection_tries_next_distribution_after_error_body_timeout(monkeypatch):
    alternative_url = "https://data.example/alternative.csv"
    requests = []
    failed_bodies = []

    class BrokenBody(io.BytesIO):
        def read1(self, size):
            raise TimeoutError("slow error body")

    class DataResponse(io.BytesIO):
        headers = {"Content-Type": "text/csv"}
        status = 200

        def geturl(self):
            return alternative_url

    def request(req, **kwargs):
        requests.append((req.full_url, req.get_method()))
        if req.full_url == DATA_URL:
            body = BrokenBody(b"error")
            failed_bodies.append(body)
            raise HTTPError(DATA_URL, 403, "Forbidden", {}, body)
        return DataResponse(b"country,cases\nCH,42\n")

    class Classifier:
        def classify(self, page, distributions):
            return PageClassification(accepted=True)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", request)
    result = collect_source_with_report(
        "https://data.example/dataset",
        classifier=Classifier(),
        discover=lambda _: [DiscoveredPage(
            url="https://data.example/dataset", discovery_method="test", title="Health data",
            distributions=(DistributionCandidate(DATA_URL, "CSV", 1.0),
                           DistributionCandidate(alternative_url, "CSV", .9)),
        )],
    )
    assert requests == [(DATA_URL, "HEAD"), (DATA_URL, "GET"),
                        (alternative_url, "HEAD"), (alternative_url, "GET")]
    assert len(result.datasets) == 1
    assert result.datasets[0].distributions[0].url == alternative_url
    assert result.report.validation_failures[0].status == "unconfirmed"
    assert result.report.verification_complete
    assert all(body.closed for body in failed_bodies)


@pytest.mark.parametrize("budgeted", [False, True])
@pytest.mark.parametrize("size", [20_000, 20_001, 10_000_000])
def test_sitemap_limit_applies_to_decompressed_content(monkeypatch, budgeted, size):
    class Response(io.BytesIO):
        headers = {"Content-Type": "application/gzip"}

        def geturl(self):
            return "https://data.example/sitemap.xml.gz"

    response = Response(gzip.compress(b"a" * size))
    assert len(response.getvalue()) < 20_000
    monkeypatch.setattr("collector.discovery.sitemap.open_public_http_url",
                        lambda *args, **kwargs: response)
    with collection_budget(seconds=5) if budgeted else nullcontext():
        if size > 20_000:
            with pytest.raises(ValueError, match="Decompressed sitemap is too large"):
                fetch_text_url(response.geturl(), max_bytes=20_000)
        else:
            assert fetch_text_url(response.geturl(), max_bytes=20_000) == "a" * size
    assert response.closed


def test_sitemap_limit_applies_across_multiple_gzip_members(monkeypatch):
    class Response(io.BytesIO):
        headers = {"Content-Type": "application/gzip"}

        def geturl(self):
            return "https://data.example/sitemap.xml.gz"

    response = Response(gzip.compress(b"a" * 12_000) + gzip.compress(b"b" * 12_000))
    monkeypatch.setattr("collector.discovery.sitemap.open_public_http_url",
                        lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="Decompressed sitemap is too large"):
        fetch_text_url(response.geturl(), max_bytes=20_000)
    assert response.closed


def test_truncated_gzip_sitemap_is_a_closed_controlled_failure(monkeypatch):
    class Response(io.BytesIO):
        headers = {"Content-Type": "application/gzip"}

        def geturl(self):
            return "https://data.example/sitemap.xml.gz"

    response = Response(gzip.compress(b"<urlset></urlset>")[:-8])
    monkeypatch.setattr("collector.discovery.sitemap.open_public_http_url",
                        lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="Could not fetch sitemap URL"):
        fetch_text_url(response.geturl(), max_bytes=20_000)
    assert response.closed
