from __future__ import annotations

import io
import json
import socket
import ssl
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.error import HTTPError, URLError

import pytest

from collector.budget import CollectionBudgetExceeded, collection_budget
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.collection.http import fetch_record_json

URL = "https://example.org/api/files/123"


@pytest.fixture(autouse=True)
def no_real_retry_wait(monkeypatch):
    monkeypatch.setattr("collector.collection.http.time.sleep", lambda delay: None)


class Response(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def geturl(self):
        return URL


def test_record_json_retains_actual_http_status_and_final_url(monkeypatch):
    monkeypatch.setattr(
        "collector.collection.http.open_public_http_url",
        lambda *a, **k: Response(b'{"status":"OK","data":{}}', 202),
    )
    response = fetch_record_json(URL)
    assert response.http_status == 202
    assert response.final_url == URL
    assert response.payload == {"status": "OK", "data": {}}


@pytest.mark.parametrize("body", [b"<html>Verification</html>", b"\xff", b"null", b"42"])
def test_unreadable_response_retains_successful_transport_evidence(monkeypatch, body):
    monkeypatch.setattr(
        "collector.collection.http.open_public_http_url", lambda *a, **k: Response(body)
    )
    with pytest.raises(CollectionResponseError) as caught:
        fetch_record_json(URL)
    assert caught.value.http_status == 200
    assert caught.value.phase == "decode"
    assert caught.value.diagnostics[0].code == "repository_invalid_json"


def test_oversized_response_remains_bounded(monkeypatch):
    response = Response(b"{}SECRET")
    monkeypatch.setattr("collector.collection.http.open_public_http_url", lambda *a, **k: response)
    with pytest.raises(CollectionResponseError) as caught:
        fetch_record_json(URL, max_bytes=2)
    assert caught.value.http_status == 200
    assert caught.value.diagnostics[0].code == "repository_response_too_large"


@pytest.mark.parametrize(
    "error,code",
    [
        (
            HTTPError(URL, 403, "secret provider text", {}, io.BytesIO(b"secret")),
            "repository_http_error",
        ),
        (URLError("secret transport text"), "repository_network_error"),
        (URLError(TimeoutError("secret timeout")), "repository_timeout"),
        (socket.timeout("secret socket timeout"), "repository_timeout"),
        (URLError(socket.timeout("secret socket timeout")), "repository_timeout"),
    ],
)
def test_transport_failures_are_distinct_and_controlled(monkeypatch, error, code):
    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr("collector.collection.http.open_public_http_url", failed)
    with pytest.raises(CollectionTransportError) as caught:
        fetch_record_json(URL)
    exc = caught.value
    assert exc.diagnostics[0].code == code
    assert exc.http_status == (403 if isinstance(error, HTTPError) else None)
    assert "secret" not in json.dumps(exc.diagnostics[0].to_dict())


def test_expired_budget_does_not_hide_behind_network_failure(monkeypatch):
    def failed(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("collector.collection.http.open_public_http_url", failed)
    with collection_budget(seconds=-1), pytest.raises(CollectionBudgetExceeded):
        fetch_record_json(URL)


def test_body_read_timeout_preserves_received_headers(monkeypatch):
    class SlowResponse(Response):
        def read(self, *args):
            raise TimeoutError("private provider text")
    monkeypatch.setattr(
        "collector.collection.http.open_public_http_url", lambda *a, **k: SlowResponse(b""),
    )
    with pytest.raises(CollectionTransportError) as caught:
        fetch_record_json(URL)
    assert caught.value.http_status == 200 and caught.value.final_url == URL
    assert caught.value.diagnostics[0].code == "repository_timeout"


@pytest.mark.parametrize("error", [
    URLError(TimeoutError()), socket.timeout(), URLError(socket.timeout()),
    URLError(ConnectionResetError()),
    URLError(socket.gaierror(socket.EAI_AGAIN, "temporary DNS failure")),
    HTTPError(URL, 429, "rate limited", {"Retry-After": "2"}, io.BytesIO()),
    HTTPError(URL, 503, "unavailable", {}, io.BytesIO()),
])
def test_transient_metadata_error_retries_then_succeeds(monkeypatch, error):
    calls, sleeps = [], []

    def open_request(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            raise error
        return Response(b'{"files":[]}')

    monkeypatch.setattr("collector.collection.http.open_public_http_url", open_request)
    monkeypatch.setattr("collector.collection.http.time.sleep", sleeps.append)
    response = fetch_record_json(URL)
    assert response.request_attempts == 2
    assert len(calls) == 2 and len(sleeps) == 1 and sleeps[0] >= 1
    if isinstance(error, HTTPError):
        assert error.fp.closed


@pytest.mark.parametrize("error", [
    HTTPError(URL, 403, "forbidden", {}, io.BytesIO()),
    HTTPError(URL, 406, "not acceptable", {}, io.BytesIO()),
    URLError(ssl.SSLCertVerificationError("bad certificate")),
    URLError(socket.gaierror(socket.EAI_NONAME, "unknown host")),
])
def test_permanent_failures_are_not_retried(monkeypatch, error):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise error

    monkeypatch.setattr("collector.collection.http.open_public_http_url", fail)
    monkeypatch.setattr("collector.collection.http.time.sleep", lambda _: pytest.fail("wait"))
    with pytest.raises(CollectionTransportError) as caught:
        fetch_record_json(URL)
    assert calls == [1] and caught.value.request_attempts == 1


def test_network_retries_are_bounded_and_keep_last_error(monkeypatch):
    calls, sleeps = [], []

    def fail(*args, **kwargs):
        calls.append(1)
        raise ConnectionResetError("private transport text")

    monkeypatch.setattr("collector.collection.http.open_public_http_url", fail)
    monkeypatch.setattr("collector.collection.http.time.sleep", sleeps.append)
    with pytest.raises(CollectionTransportError) as caught:
        fetch_record_json(URL)
    assert len(calls) == 3 and sleeps == [1, 2]
    assert caught.value.request_attempts == 3
    assert caught.value.diagnostics[0].attempt == 3
    assert "private" not in json.dumps(caught.value.diagnostics[0].to_dict())


@pytest.mark.parametrize("header", [
    "120", format_datetime(datetime.now(timezone.utc) + timedelta(minutes=2)),
])
def test_long_retry_after_is_preserved_without_shortening(monkeypatch, header):
    def fail(*args, **kwargs):
        raise HTTPError(URL, 429, "limited", {"Retry-After": header}, io.BytesIO())

    monkeypatch.setattr("collector.collection.http.open_public_http_url", fail)
    monkeypatch.setattr("collector.collection.http.time.sleep", lambda _: pytest.fail("wait"))
    with pytest.raises(CollectionTransportError) as caught:
        fetch_record_json(URL)
    assert caught.value.request_attempts == 1
    assert caught.value.diagnostics[0].retry_at is not None


def test_retry_wait_cannot_overrun_collection_deadline(monkeypatch):
    clock, calls = [100.0], []
    monkeypatch.setattr("collector.budget.monotonic", lambda: clock[0])

    def fail(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()

    def sleep(delay):
        clock[0] += delay + 1  # Also simulate an overdue scheduler wakeup.

    monkeypatch.setattr("collector.collection.http.open_public_http_url", fail)
    monkeypatch.setattr("collector.collection.http.time.sleep", sleep)
    with collection_budget(seconds=2), pytest.raises(CollectionBudgetExceeded):
        fetch_record_json(URL)
    assert calls == [1]


def test_retry_after_exceeding_remaining_budget_does_not_wait(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPError(URL, 503, "unavailable", {"Retry-After": "10"}, io.BytesIO())

    monkeypatch.setattr("collector.collection.http.open_public_http_url", fail)
    monkeypatch.setattr("collector.collection.http.time.sleep", lambda _: pytest.fail("wait"))
    with collection_budget(seconds=5), pytest.raises(CollectionTransportError) as caught:
        fetch_record_json(URL)
    assert caught.value.request_attempts == 1


@pytest.mark.parametrize("kwargs", [
    {"timeout": float("nan")}, {"timeout": 0}, {"max_attempts": 4},
    {"max_attempts": True}, {"max_retry_wait": float("inf")},
])
def test_invalid_transport_configuration_fails_before_network(monkeypatch, kwargs):
    monkeypatch.setattr(
        "collector.collection.http.open_public_http_url", lambda *a, **k: pytest.fail("network"),
    )
    with pytest.raises(ValueError):
        fetch_record_json(URL, **kwargs)
