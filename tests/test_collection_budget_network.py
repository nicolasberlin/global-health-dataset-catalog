"""A collection deadline must bound requests without weakening network safety."""

from __future__ import annotations

import io
import json
import socket
from email.message import Message
from urllib.error import URLError
from urllib.request import Request

import pytest

from collector.budget import CollectionBudgetExceeded, collection_budget, read_with_budget
from collector.classification.llm_client import HTTPJSONLLMClient, LLMProviderConfig
from collector.classification.page import PageClassificationError
from collector.discovery.adapters.shared import fetch_json_url
from collector.discovery.sitemap import fetch_text_url
from collector.fetch import (
    _connect_public,
    _PublicHTTPRedirectHandler,
    _PublicHTTPSConnection,
    fetch_public_html,
    open_public_http_url,
)
from collector.storage.models import DistributionCandidate, HTTPProbe
from collector.validation.downloads import probe_url, validate_distribution


@pytest.fixture
def clock(monkeypatch):
    values = [100.0]
    monkeypatch.setattr("collector.budget.monotonic", lambda: values[0])
    return values


def address(ip="93.184.216.34"):
    return socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443)


class Socket:
    def __init__(self, connect=lambda: None):
        self.on_connect = connect
        self.closed = False
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def connect(self, _destination):
        self.on_connect()

    def close(self):
        self.closed = True


def test_expired_budget_prevents_dns(clock, monkeypatch):
    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", lambda *a, **kw: pytest.fail("DNS"))
    with collection_budget(seconds=1):
        clock[0] += 1
        with pytest.raises(CollectionBudgetExceeded):
            open_public_http_url(Request("https://public.example/data"), timeout=10)


def test_expiry_during_dns_prevents_socket_creation(clock, monkeypatch):
    def resolve(*args, **kwargs):
        clock[0] += 2
        return [address()]

    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", resolve)
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: pytest.fail("Socket"))
    with collection_budget(seconds=1), pytest.raises(CollectionBudgetExceeded):
        _connect_public("public.example", 443, 10)


@pytest.mark.parametrize("request_timeout, expected", [(10, 3), (2, 2)])
def test_connect_timeout_uses_remaining_budget_after_dns(
    clock,
    monkeypatch,
    request_timeout,
    expected,
):
    def resolve(*args, **kwargs):
        clock[0] += 2
        return [address()]

    sock = Socket()
    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", resolve)
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: sock)
    with collection_budget(seconds=5):
        assert _connect_public("public.example", 443, request_timeout) is sock
    assert sock.timeouts == [expected]


@pytest.mark.parametrize("fails", [False, True])
def test_expiry_during_connect_closes_socket_without_trying_next_ip(clock, monkeypatch, fails):
    def connect():
        clock[0] += 2
        if fails:
            raise TimeoutError("connect timed out")

    sock = Socket(connect)
    sockets = []

    def create(*args):
        sockets.append(sock)
        return sock

    monkeypatch.setattr(
        "collector.fetch.socket.getaddrinfo",
        lambda *a, **kw: [address(), address("93.184.216.35")],
    )
    monkeypatch.setattr("collector.fetch.socket.socket", create)
    with collection_budget(seconds=1), pytest.raises(CollectionBudgetExceeded):
        _connect_public("public.example", 443, 10)
    assert sock.closed
    assert len(sockets) == 1


def test_tls_uses_remaining_budget_and_hostname_and_closes_on_expiry(clock, monkeypatch):
    sock = Socket(lambda: clock.__setitem__(0, clock[0] + 2))
    handshakes = []

    class TLS:
        def set_alpn_protocols(self, protocols):
            assert protocols == ["http/1.1"]

        def wrap_socket(self, connection, *, server_hostname):
            handshakes.append(server_hostname)
            clock[0] += 3
            return connection

    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", lambda *a, **kw: [address()])
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: sock)
    monkeypatch.setattr("collector.fetch.ssl.create_default_context", TLS)
    with collection_budget(seconds=5), pytest.raises(CollectionBudgetExceeded):
        _PublicHTTPSConnection("public.example", timeout=10).connect()
    assert sock.timeouts == [5, 3]
    assert handshakes == ["public.example"]
    assert sock.closed


def test_expired_budget_stops_redirect(clock):
    with collection_budget(seconds=1):
        clock[0] += 1
        with pytest.raises(CollectionBudgetExceeded):
            _PublicHTTPRedirectHandler().redirect_request(
                Request("https://public.example/old"),
                None,
                302,
                "Found",
                Message(),
                "https://public.example/new",
            )


@pytest.mark.parametrize("head_duration, expected_timeouts", [(2, [5, 3]), (5, [5])])
def test_validation_rechecks_budget_between_head_and_get(clock, head_duration, expected_timeouts):
    calls = []

    def probe(url, *, method, timeout, **kwargs):
        calls.append(timeout)
        if method == "HEAD":
            clock[0] += head_duration
        return HTTPProbe(url, url, 200, {"content-type": "text/csv"}, b"age,count\n20,4\n")

    item = DistributionCandidate("https://public.example/data.csv", "CSV", 0.9)
    with collection_budget(seconds=5):
        if head_duration == 5:
            with pytest.raises(CollectionBudgetExceeded):
                validate_distribution(item, timeout=10, probe=probe)
        else:
            assert validate_distribution(item, timeout=10, probe=probe).ok
    assert calls == expected_timeouts


@pytest.mark.parametrize(
    "module, call",
    [
        ("collector.fetch", lambda: fetch_public_html("https://public.example/page")),
        (
            "collector.discovery.adapters.shared",
            lambda: fetch_json_url("https://public.example/json"),
        ),
        ("collector.discovery.sitemap", lambda: fetch_text_url("https://public.example/sitemap")),
        (
            "collector.validation.downloads",
            lambda: probe_url(
                "https://public.example/data",
                method="GET",
                timeout=10,
                max_bytes=100,
            ),
        ),
    ],
)
def test_transport_timeout_at_deadline_remains_a_budget_failure(clock, monkeypatch, module, call):
    def request(*args, **kwargs):
        clock[0] += 1
        raise URLError(TimeoutError("request timed out"))

    monkeypatch.setattr(f"{module}.open_public_http_url", request)
    with collection_budget(seconds=1), pytest.raises(CollectionBudgetExceeded):
        call()


def llm_client(request):
    return HTTPJSONLLMClient(
        provider=LLMProviderConfig(
            name="Test",
            endpoint_url="https://llm.example/classify",
            api_key_env_var="TEST_KEY",
            model_env_var="TEST_MODEL",
            default_model="test",
            request_body_builder=lambda payload, model: payload,
            response_text_extractor=lambda body: body["text"],
        ),
        api_key="test",
        timeout_seconds=20,
        request=request,
    )


def test_llm_request_respects_remaining_timeout(clock):
    timeouts = []

    def request(_request, *, timeout):
        timeouts.append(timeout)
        return io.BytesIO(json.dumps({"text": '{"accepted":true}'}).encode())

    with collection_budget(seconds=5):
        clock[0] += 2
        assert llm_client(request).classify_page({}) == {"accepted": True}
    assert timeouts == [3]


def test_llm_request_does_not_start_after_deadline(clock):
    client = llm_client(lambda *a, **kw: pytest.fail("Provider request"))
    with collection_budget(seconds=1):
        clock[0] += 1
        with pytest.raises(CollectionBudgetExceeded):
            client.classify_page({})


@pytest.mark.parametrize(
    "duration, expected", [(1, PageClassificationError), (5, CollectionBudgetExceeded)]
)
def test_llm_timeout_is_retryable_only_while_collection_has_time(clock, duration, expected):
    def request(*args, **kwargs):
        clock[0] += duration
        raise TimeoutError("provider timeout")

    with collection_budget(seconds=5), pytest.raises(expected) as caught:
        llm_client(request).classify_page({})
    assert caught.value.diagnostics[0].code == (
        "llm_timeout" if duration < 5 else "collection_budget_exhausted"
    )


def test_slow_stream_stops_between_reads(clock):
    reads = []

    class Stream:
        def read(self, size):
            pytest.fail("Blocking read should not be used when read1 exists")

        def read1(self, size):
            reads.append(size)
            clock[0] += 1
            return b"x"

    with collection_budget(seconds=2), pytest.raises(CollectionBudgetExceeded):
        read_with_budget(Stream(), 100)
    assert len(reads) == 2


def test_bounded_read_preserves_lookahead_limit(clock):
    with collection_budget(seconds=5):
        assert read_with_budget(io.BytesIO(b"123456789"), 5) == b"12345"


@pytest.mark.parametrize("url", ["https://public.example/next", "http://127.0.0.1/private"])
def test_redirect_closes_body_without_draining_it(clock, url):
    class Body:
        closed = False

        def close(self):
            self.closed = True

        def read(self, *args):
            assert self.closed, "The redirect body must not be drained"
            return b""

    body = Body()
    with collection_budget(seconds=5):
        handler = _PublicHTTPRedirectHandler()
        if "127.0.0.1" in url:
            with pytest.raises(ValueError):
                handler.redirect_request(
                    Request("https://public.example"), body, 302, "Found", Message(), url
                )
        else:
            request = handler.redirect_request(
                Request("https://public.example", method="HEAD"), body, 302, "Found", Message(), url
            )
            assert request.get_method() == "HEAD"
            assert body.read() == b""  # urllib's subsequent drain sees a closed response.
    assert body.closed


def test_http_error_sample_closes_response_on_expiration(clock, monkeypatch):
    from urllib.error import HTTPError

    class Body(io.BytesIO):
        def read1(self, size):
            clock[0] += 5
            return b"x"

    body = Body(b"error")

    def request(*args, **kwargs):
        raise HTTPError("https://public.example/data", 403, "Forbidden", {}, body)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", request)
    with collection_budget(seconds=5), pytest.raises(CollectionBudgetExceeded):
        probe_url("https://public.example/data", method="GET", timeout=10, max_bytes=100)
    assert body.closed


def test_complete_response_is_retained_when_final_read_reaches_deadline(clock):
    class CompleteResponse(io.BytesIO):
        length = 2

        def read1(self, size):
            clock[0] += 5
            self.length = 0
            return super().read1(size)

    with collection_budget(seconds=5):
        assert read_with_budget(CompleteResponse(b"ok"), 100) == b"ok"
