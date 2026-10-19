"""Real urllib/HTTPResponse parsing over fragmented, clocked in-memory sockets."""

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

from collector.budget import (
    CollectionBudgetExceeded,
    active_request_budget,
    collection_budget,
)
from collector.classification.llm_client import HTTPJSONLLMClient, LLMProviderConfig
from collector.classification.page import PageClassificationError
from collector.collection.browser import BrowserSession
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.collection.http import fetch_record_json
from collector.config import DEFAULT_CONFIG
from collector.discovery.adapters.shared import fetch_json_url
from collector.discovery.sitemap import fetch_text_url
from collector.execution import ExecutionControl, ExecutionStopped, execution_control
from collector.fetch import (
    PageFetchError,
    decode_text_body,
    fetch_public_html,
    open_public_http_url,
)


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("collector.budget.monotonic", lambda: now[0])
    return now


class FragmentedBody(io.RawIOBase):
    def __init__(self, clock, chunks, on_read=lambda: None):
        self.clock, self.chunks, self.on_read = clock, iter(chunks), on_read

    def readable(self):
        return True

    def readinto(self, target):
        self.on_read()
        try:
            delay, data = next(self.chunks)
        except StopIteration:
            return 0
        self.clock[0] += delay
        assert len(data) <= len(target)
        target[:len(data)] = data
        return len(data)


class ClockedSocket:
    def __init__(self, body):
        self.body, self.timeout, self.closed = body, None, False
        self.sent = b""

    def settimeout(self, timeout):
        self.timeout = timeout

    def gettimeout(self):
        return self.timeout

    def connect(self, address):
        self.address = address

    def sendall(self, data):
        self.sent += data

    def setsockopt(self, *args):
        pass

    def makefile(self, *args):
        return self.body

    def close(self):
        self.closed = True


def install_sockets(monkeypatch, connections):
    values = iter(connections)
    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", lambda host, port, *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port)),
    ])
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *args: next(values))


@pytest.mark.parametrize("phase", ["status", "headers", "body", "chunk_headers"])
@pytest.mark.parametrize("collection_seconds", [None, 3])
def test_absolute_deadline_bounds_every_http_read_without_inactivity_timeout(
    monkeypatch, clock, phase, collection_seconds,
):
    prefixes = {
        "status": b"",
        "headers": b"HTTP/1.1 200 OK\r\n",
        "body": b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n",
        "chunk_headers": b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
    }
    # Each byte arrives before the original socket timeout, but the exchange
    # must still end at the one absolute deadline.
    stream = FragmentedBody(
        clock, ([(0, prefixes[phase])] if prefixes[phase] else []) + [(1, b"x")] * 20,
    )
    connection = ClockedSocket(stream)
    install_sockets(monkeypatch, [connection])

    def run():
        with open_public_http_url(Request("http://public.example/data"), timeout=5) as response:
            assert active_request_budget() is None  # The response retains its deadline.
            response.read(20)

    if collection_seconds is None:
        with pytest.raises((URLError, TimeoutError)) as caught:
            run()
        error = getattr(caught.value, "reason", caught.value)
        assert isinstance(error, TimeoutError)
        assert clock[0] == 5
    else:
        with collection_budget(seconds=collection_seconds), pytest.raises(CollectionBudgetExceeded):
            run()
        assert clock[0] == collection_seconds
    assert stream.closed and connection.closed


@pytest.mark.parametrize("prefix", [
    b"", b"HTTP/1.1 200 OK\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
])
def test_real_socket_trickle_is_stopped_at_the_absolute_deadline(monkeypatch, prefix):
    client, server = socket.socketpair()
    server.settimeout(1)
    stop = threading.Event()

    def serve():
        try:
            with server:
                server.recv(8192)
                if prefix:
                    server.sendall(prefix)
                for _ in range(30):
                    if stop.wait(0.03):
                        return
                    server.sendall(b"1")
        except OSError:
            pass  # Client closes its transport at the deadline.

    monkeypatch.setattr("collector.fetch._connect_public", lambda *a: client)
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises((TimeoutError, URLError)):
            with open_public_http_url(Request("http://public.example/"), timeout=0.15) as response:
                response.read(100)
        assert time.monotonic() - started < 0.6
    finally:
        stop.set()
        client.close()
        thread.join(timeout=2)
        server.close()
    assert not thread.is_alive()


def test_redirects_share_one_request_deadline(monkeypatch, clock):
    first = ClockedSocket(FragmentedBody(clock, [
        (3, b"HTTP/1.1 302 Found\r\nLocation: /second\r\nContent-Length: 0\r\n\r\n"),
    ]))
    second = ClockedSocket(FragmentedBody(clock, [
        (3, b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"),
    ]))
    install_sockets(monkeypatch, [first, second])
    with pytest.raises((URLError, TimeoutError)):
        open_public_http_url(Request("http://public.example/start"), timeout=5)
    assert first.body.closed and second.body.closed
    assert first.closed and second.closed
    assert second.timeout <= 2


def test_dns_result_arriving_after_deadline_cannot_start_a_connection(monkeypatch, clock):
    def lookup(*args, **kwargs):
        clock[0] += 6
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 80))]

    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", lookup)
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: pytest.fail("late socket"))
    with pytest.raises((URLError, TimeoutError)):
        open_public_http_url(Request("http://public.example/"), timeout=5)
    assert clock[0] == 6


def test_cancellation_during_headers_closes_the_socket(monkeypatch, clock):
    control = ExecutionControl()
    stream = FragmentedBody(clock, [(0, b"HTTP/1.1 200 OK\r\n")], control.abort)
    connection = ClockedSocket(stream)
    install_sockets(monkeypatch, [connection])
    token = execution_control.set(control)
    try:
        with pytest.raises(ExecutionStopped):
            open_public_http_url(Request("http://public.example/"), timeout=5)
    finally:
        execution_control.reset(token)
    assert stream.closed and connection.closed


def llm_client():
    return HTTPJSONLLMClient(
        provider=LLMProviderConfig(
            name="Test", endpoint_url="http://provider.example/classify",
            api_key_env_var="TEST_UNUSED_KEY", model_env_var="TEST_UNUSED_MODEL",
            default_model="test", request_body_builder=lambda payload, model: payload,
            response_text_extractor=lambda body: body["text"],
        ), api_key="synthetic-test-token", timeout_seconds=5,
    )


def test_default_llm_transport_also_bounds_slow_headers(monkeypatch, clock):
    stream = FragmentedBody(clock, [(0, b"HTTP/1.1 200 OK\r\n")] + [(1, b"x")] * 20)
    connection = ClockedSocket(stream)
    install_sockets(monkeypatch, [connection])
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    with pytest.raises(PageClassificationError) as caught:
        llm_client().classify_page({})
    assert caught.value.diagnostics[0].code == "llm_timeout"
    assert clock[0] == 5 and stream.closed and connection.closed


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("expired", [False, True])
def test_browser_control_redirect_never_forwards_token_and_always_closes(
    monkeypatch, clock, status, expired,
):
    requests, bodies = [], []

    class RedirectingTransport(HTTPHandler):
        def http_open(self, request):
            requests.append((request.full_url, request.get_method(),
                             request.get_header("Authorization")))
            headers = Message()
            headers["Location"] = "http://unrelated.example/steal"
            response = addinfourl(io.BytesIO(b"redirect"), headers, request.full_url, status)
            response.msg = "Redirect"
            bodies.append(response)
            if expired:
                clock[0] += 5
            return response

    monkeypatch.setattr("collector.collection.browser.build_opener",
                        lambda *handlers: build_opener(RedirectingTransport(), *handlers))
    session = BrowserSession("http://renderer.example", "synthetic-test-token", DEFAULT_CONFIG)
    expected = CollectionBudgetExceeded if expired else CollectionTransportError
    with collection_budget(seconds=5), pytest.raises(expected):
        session.request("/render", {"url": "https://dataverse.harvard.edu/"})
    assert requests == [("http://renderer.example/render", "POST", "Bearer synthetic-test-token")]
    assert len(bodies) == 1 and bodies[0].closed


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}

    def geturl(self):
        return "https://public.example/data"


def test_browser_lease_uses_collection_budget_instead_of_request_deadline(monkeypatch, clock):
    payloads = []

    class Renderer:
        def open(self, request, **kwargs):
            payloads.append(json.loads(request.data))
            return Response(b"{}")

    monkeypatch.setattr("collector.collection.browser.build_opener", lambda *a: Renderer())
    session = BrowserSession("http://renderer.example", "synthetic-test-token", DEFAULT_CONFIG)
    with collection_budget(seconds=300):
        session.request("/render", {"url": "https://dataverse.harvard.edu/"})
    assert payloads[0]["budget_ms"] == 300_000


def test_browser_cleanup_remains_bounded_after_owner_expiry_and_cancellation(monkeypatch, clock):
    calls = []

    class Renderer:
        def open(self, request, **kwargs):
            calls.append(request.full_url)
            return Response(b"{}")

    monkeypatch.setattr("collector.collection.browser.build_opener", lambda *a: Renderer())
    control = ExecutionControl()
    token = execution_control.set(control)
    session = BrowserSession("http://renderer.example", "synthetic-test-token", DEFAULT_CONFIG)
    session.session_id = "synthetic-session"
    try:
        with collection_budget(seconds=1):
            clock[0] += 2
            control.abort()
            session.close()
            assert execution_control.get() is control
    finally:
        execution_control.reset(token)
    assert calls == ["http://renderer.example/close"] and session.session_id is None


@pytest.mark.parametrize("module,call", [
    ("collector.fetch", lambda: fetch_public_html("https://public.example/")),
    ("collector.discovery.adapters.shared", lambda: fetch_json_url("https://public.example/")),
    ("collector.collection.http", lambda: fetch_record_json("https://public.example/")),
    ("collector.discovery.sitemap", lambda: fetch_text_url("https://public.example/")),
])
@pytest.mark.parametrize("expired", [False, True])
def test_http_error_closes_even_when_budget_check_raises(monkeypatch, clock, module, call, expired):
    body = io.BytesIO(b"provider error")

    def fail(*args, **kwargs):
        if expired:
            clock[0] += 5
        raise HTTPError("https://public.example/", 403, "Forbidden", {}, body)

    monkeypatch.setattr(module + ".open_public_http_url", fail)
    expected = CollectionBudgetExceeded if expired else (PageFetchError, ValueError)
    with collection_budget(seconds=5), pytest.raises(expected):
        call()
    assert body.closed


@pytest.mark.parametrize("transport", ["metadata", "discovery", "browser"])
def test_deep_remote_json_is_a_controlled_failure(monkeypatch, transport):
    levels = sys.getrecursionlimit() + 100
    body = Response(("[" * levels + "0" + "]" * levels).encode())
    if transport == "browser":
        class Renderer:
            def open(self, *args, **kwargs):
                return body

        monkeypatch.setattr("collector.collection.browser.build_opener", lambda *a: Renderer())
        def call():
            return BrowserSession("http://renderer", "synthetic", DEFAULT_CONFIG).request(
                "/render", {"url": "https://dataverse.harvard.edu/"},
            )
        expected = CollectionResponseError
    else:
        module = "collector.collection.http" if transport == "metadata" else (
            "collector.discovery.adapters.shared"
        )
        monkeypatch.setattr(module + ".open_public_http_url", lambda *a, **k: body)
        def call():
            return (fetch_record_json if transport == "metadata" else fetch_json_url)(
                "https://public.example/",
            )
        expected = CollectionResponseError if transport == "metadata" else ValueError
    with pytest.raises(expected):
        call()
    assert body.closed


@pytest.mark.parametrize("content_type", [
    "text/html; charset=x-not-an-encoding", "text/xml; charset=base64_codec",
])
def test_unknown_or_non_text_encoding_is_a_controlled_failure(content_type):
    with pytest.raises(ValueError, match="text encoding is invalid"):
        decode_text_body(b"example", content_type)


def test_quoted_charset_is_supported():
    assert decode_text_body(b"caf\xe9", 'text/html; charset="iso-8859-1"') == "café"
