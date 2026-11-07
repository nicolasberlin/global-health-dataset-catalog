"""Explicit origin configuration for independently hosted browser clients."""

import pytest
from app.auth.security import api_cors_origins


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.org",
        "http://example.org",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]",
        "http://[::1]:5173",
        "https://example.org:8443",
    ],
)
def test_cors_accepts_valid_origins(monkeypatch, origin):
    monkeypatch.setenv("API_CORS_ORIGINS", origin)

    assert api_cors_origins() == [origin]


@pytest.mark.parametrize(
    "configured, expected",
    [
        (
            "https://a.example,https://b.example",
            ["https://a.example", "https://b.example"],
        ),
        (
            " https://example.org ",
            ["https://example.org"],
        ),
        (
            "https://a.example,https://a.example",
            ["https://a.example"],
        ),
        (
            "",
            [],
        ),
    ],
)
def test_cors_normalizes_valid_configuration(monkeypatch, configured, expected):
    monkeypatch.setenv("API_CORS_ORIGINS", configured)

    assert api_cors_origins() == expected


def test_cors_uses_default_origins(monkeypatch):
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

    assert api_cors_origins() == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        # Invalid origins
        "*",
        "ftp://example.org",
        "file://example.org",
        "example.org",
        "https://",
        "https://exa mple.org",
        "https://example.org/path",
        "https://example.org?query=1",
        "https://example.org#section",
        "https://user@host",
        "https://user:pass@host",
        "https://host:invalid",
        "https://host:99999",
        "https://example.org\\evil",
        "https://[broken",
    ],
)
def test_cors_invalid_configuration_fails_early(monkeypatch, origin):
    monkeypatch.setenv("API_CORS_ORIGINS", origin)
    with pytest.raises(RuntimeError, match="API_CORS_ORIGINS"):
        api_cors_origins()


@pytest.mark.parametrize(
    "origin",
    [
        "https://@example.org",
        "https://exa<mple.org",
        "https://example.org:",
        "http://[::1]:",
        "https://exa\nmple.org",
    ],
)
def test_cors_rejects_malformed_origins(monkeypatch, origin):
    monkeypatch.setenv("API_CORS_ORIGINS", origin)

    with pytest.raises(RuntimeError, match="API_CORS_ORIGINS"):
        api_cors_origins()


def test_cors_rejects_backslash_in_ipv6_origin(monkeypatch):
    monkeypatch.setenv(
        "API_CORS_ORIGINS",
        r"https://[fe80::1%25\evil]",
    )

    with pytest.raises(RuntimeError, match="API_CORS_ORIGINS"):
        api_cors_origins()


def test_cors_rejects_invalid_second_origin(monkeypatch):
    monkeypatch.setenv(
        "API_CORS_ORIGINS",
        "https://good.org,ftp://bad.org",
    )

    with pytest.raises(RuntimeError):
        api_cors_origins()


@pytest.mark.parametrize(
    "origin",
    [
        "https://-example.org",  # Leading hyphen
        "https://example-.org",  # Trailing hyphen
        "https://exa_mple.org",  # Underscore not allowed
    ],
)
def test_cors_rejects_invalid_hostname_labels(monkeypatch, origin):
    monkeypatch.setenv("API_CORS_ORIGINS", origin)

    with pytest.raises(RuntimeError, match="API_CORS_ORIGINS"):
        api_cors_origins()


@pytest.mark.parametrize(
    "last_label_length, accepted",
    [
        (61, True),  # 253-character hostname
        (62, False),  # 254-character hostname
    ],
)
def test_cors_hostname_length_limit(monkeypatch, last_label_length, accepted):
    hostname = ".".join(["a" * 63] * 3 + ["a" * last_label_length])
    origin = f"https://{hostname}"

    monkeypatch.setenv("API_CORS_ORIGINS", origin)

    if accepted:
        assert api_cors_origins() == [origin]
    else:
        with pytest.raises(RuntimeError):
            api_cors_origins()


@pytest.mark.parametrize(
    "label_length, accepted",
    [
        (63, True),
        (64, False),
    ],
)
def test_cors_hostname_label_length_limit(monkeypatch, label_length, accepted):
    origin = f"https://{'a' * label_length}.org"

    monkeypatch.setenv("API_CORS_ORIGINS", origin)

    if accepted:
        assert api_cors_origins() == [origin]
    else:
        with pytest.raises(RuntimeError):
            api_cors_origins()
