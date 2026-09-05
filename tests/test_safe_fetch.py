from __future__ import annotations

from email.message import Message
from urllib.request import Request

import pytest

from collector.fetch import _PublicHTTPRedirectHandler, open_public_http_url
from collector.validation.downloads import probe_url


def test_public_http_fetch_blocks_private_url_before_opening(monkeypatch):
    opened = False

    def fail_if_opened(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("A private URL must not be opened.")

    monkeypatch.setattr("collector.fetch.build_opener", fail_if_opened)

    with pytest.raises(ValueError, match="Private or local"):
        open_public_http_url(Request("http://127.0.0.1/private"), timeout=1)

    assert opened is False


def test_public_http_redirect_handler_blocks_private_destination():
    handler = _PublicHTTPRedirectHandler()

    with pytest.raises(ValueError, match="Private or local"):
        handler.redirect_request(
            Request("https://public.example/file.csv"),
            None,
            302,
            "Found",
            Message(),
            "http://127.0.0.1/private",
        )


def test_distribution_probe_reports_private_url_as_invalid(monkeypatch):
    monkeypatch.setattr(
        "collector.fetch.build_opener",
        lambda *args, **kwargs: pytest.fail("A private distribution must not be opened."),
    )

    result = probe_url(
        "http://127.0.0.1/private.csv",
        method="HEAD",
        timeout=1,
        max_bytes=0,
    )

    assert result.status_code is None
    assert "Private or local" in result.error
