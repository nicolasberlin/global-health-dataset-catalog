from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from collector.budget import CollectionBudgetExceeded, collection_budget
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.collection.http import fetch_record_json

URL = "https://example.org/api/files/123"


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
