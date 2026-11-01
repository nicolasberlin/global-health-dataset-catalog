"""Bounded JSON fetch regressions with local documents and controlled transport errors."""

from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from collector.budget import CollectionBudgetExceeded
from collector.network.json import fetch_json_url


class Response(io.BytesIO):
    def __init__(self, body: bytes, final_url: str):
        super().__init__(body)
        self.final_url = final_url

    def geturl(self):
        return self.final_url






















@pytest.mark.parametrize("body", [
    b'{"title":"\xff"}',
    b'{"missing":}',
    b'{"nested":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
])
def test_malformed_or_deep_json_is_controlled_and_closes_response(monkeypatch, body):
    response = Response(body, "https://catalog.example/data.json")
    monkeypatch.setattr(
        "collector.network.json.open_public_http_url",
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

    monkeypatch.setattr("collector.network.json.open_public_http_url", fail)
    monkeypatch.setattr("collector.network.json.check_collection_budget", budget)
    with pytest.raises(CollectionBudgetExceeded if exhausted else ValueError):
        fetch_json_url("https://catalog.example/data.json")
    assert body.closed
