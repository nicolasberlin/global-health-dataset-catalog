"""Explicit origin configuration for independently hosted browser clients."""

import pytest
from app.security import api_cors_origins


def test_cors_origins_support_separate_frontends_and_server_only(monkeypatch):
    monkeypatch.setenv(
        "API_CORS_ORIGINS", "https://example.org,http://localhost:3000,https://example.org"
    )
    assert api_cors_origins() == ["https://example.org", "http://localhost:3000"]
    monkeypatch.setenv("API_CORS_ORIGINS", "")
    assert api_cors_origins() == []


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://example.org/path",
        "https://user@host",
        "file://host",
        "https://[broken",
        "https://host:invalid",
    ],
)
def test_cors_invalid_configuration_fails_early(monkeypatch, origin):
    monkeypatch.setenv("API_CORS_ORIGINS", origin)
    with pytest.raises(RuntimeError, match="API_CORS_ORIGINS"):
        api_cors_origins()
