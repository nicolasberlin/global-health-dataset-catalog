from __future__ import annotations

import pytest
from app.auth.security import (
    APIPrincipal,
    configure_access_openapi,
    enforce_api_quota,
    require_api_principal,
    validate_api_security_configuration,
)
from app.quota_policy import QuotaExceeded, QuotaLimit
from app.routes.collector import router
from fastapi import FastAPI, HTTPException, Request, Response

pytestmark = pytest.mark.anyio


def _request(host="127.0.0.1", origin=None, hostname="127.0.0.1", extra=()):
    headers = [(b"host", hostname.encode()), *extra]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "client": (host, 1234),
            "server": ("127.0.0.1", 8001),
            "headers": headers,
        }
    )


async def test_local_access_is_default_and_needs_no_token(monkeypatch):
    monkeypatch.delenv("API_AUTH_MODE", raising=False)
    validate_api_security_configuration()
    assert await require_api_principal(_request(), Response()) == APIPrincipal("local-user")


@pytest.mark.parametrize(
    "overrides",
    [
        {"host": "192.168.1.10"},
        {"origin": "https://evil.example"},
        {"hostname": "evil.example"},
        {"origin": "null"},
        {"extra": [(b"x-forwarded-for", b"127.0.0.1")]},
        {"extra": [(b"forwarded", b"for=127.0.0.1")]},
    ],
)
async def test_local_access_rejects_remote_clients_and_browser_origins(monkeypatch, overrides):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    with pytest.raises(HTTPException) as error:
        await require_api_principal(_request(**overrides), Response())
    assert error.value.status_code == 403


@pytest.mark.parametrize("mode", ["unknown", ""])
def test_unsupported_access_modes_fail_startup(monkeypatch, mode):
    monkeypatch.setenv("API_AUTH_MODE", mode)
    with pytest.raises(RuntimeError, match="local or public"):
        validate_api_security_configuration()


async def test_local_access_uses_peer_and_origin_even_with_an_authorization_header(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    extra = [(b"authorization", b"unused")]
    principal = await require_api_principal(_request(extra=extra), Response())
    assert principal == APIPrincipal("local-user")
    with pytest.raises(HTTPException) as error:
        await require_api_principal(_request(host="192.168.1.10", extra=extra), Response())
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "mode,origin,scheme",
    [
        ("local", None, None),
        ("public", "https://health.example", "APIKeyCookie"),
        ("public", "http://health.example", "InternalHTTPSession"),
    ],
)
def test_openapi_describes_only_the_active_access_mechanism(monkeypatch, mode, origin, scheme):
    monkeypatch.setenv("API_AUTH_MODE", mode)
    monkeypatch.setenv("API_SESSION_SECRET", "test-only-session-secret-at-least-32-characters")
    monkeypatch.setenv("API_ALLOW_INSECURE_HTTP_SESSIONS", "true")
    if origin:
        monkeypatch.setenv("API_PUBLIC_ORIGIN", origin)
    application = FastAPI()
    application.include_router(router)
    configure_access_openapi(application)
    schema = application.openapi()
    security = schema["paths"]["/collector/searches"]["post"].get("security")
    assert security == ([{scheme: []}] if scheme else None)
    assert set(schema["components"].get("securitySchemes", {})) == ({scheme} if scheme else set())
    assert "security" not in schema["paths"]["/collector/collected-datasets/by-id"]["get"]


async def test_api_quota_returns_retry_after_when_limit_is_exhausted(monkeypatch):
    async def reject_request(quotas):
        assert quotas == (QuotaLimit("test-user", "repository_search", 10),)
        raise QuotaExceeded(17)

    monkeypatch.setattr("app.auth.security.consume_quota_limits", reject_request)

    with pytest.raises(HTTPException) as error:
        await enforce_api_quota(APIPrincipal("test-user"), "repository_search")

    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "17"}


def test_source_administration_routes_are_removed():
    from app.main import app
    from starlette.routing import Match

    assert not any(path.startswith("/sources") for path in app.openapi()["paths"])
    for method, path in [("GET", "/sources"), ("POST", "/sources"), ("GET", "/sources/1/page")]:
        scope = {"type": "http", "method": method, "path": path}
        assert all(route.matches(scope)[0] == Match.NONE for route in app.routes)
