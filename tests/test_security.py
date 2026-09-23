from __future__ import annotations

import json

import pytest
from app.db.api_quotas import APIQuotaDecision
from app.security import (
    APIPrincipal,
    enforce_api_quota,
    require_api_principal,
    validate_api_security_configuration,
)
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

pytestmark = pytest.mark.anyio

VALID_TOKEN = "test-token-with-at-least-thirty-two-characters"


def _request(host="127.0.0.1", origin="http://127.0.0.1:5173", hostname="127.0.0.1"):
    return Request({
        "type": "http", "scheme": "http", "path": "/", "query_string": b"",
        "client": (host, 1234), "server": ("127.0.0.1", 8001),
        "headers": [(b"host", hostname.encode()), (b"origin", origin.encode())],
    })


async def test_local_access_needs_no_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    monkeypatch.delenv("API_ACCESS_TOKENS", raising=False)
    validate_api_security_configuration()
    assert await require_api_principal(None, _request()) == APIPrincipal("local-user")


@pytest.mark.parametrize("overrides", [
    {"host": "192.168.1.10"}, {"origin": "https://evil.example"},
    {"hostname": "evil.example"},
])
async def test_local_access_rejects_remote_clients_and_browser_origins(monkeypatch, overrides):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    with pytest.raises(HTTPException) as error:
        await require_api_principal(None, _request(**overrides))
    assert error.value.status_code == 403


def _configure_access_token(monkeypatch) -> None:
    monkeypatch.setenv(
        "API_ACCESS_TOKENS",
        json.dumps({"test-user": VALID_TOKEN}),
    )


async def test_bearer_token_authenticates_configured_owner(monkeypatch):
    _configure_access_token(monkeypatch)

    principal = await require_api_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=VALID_TOKEN), _request()
    )

    assert principal == APIPrincipal(owner_id="test-user")


@pytest.mark.parametrize(
    "credentials",
    [
        None,
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token"),
    ],
)
async def test_bearer_token_rejects_missing_or_invalid_credentials(
    monkeypatch,
    credentials,
):
    _configure_access_token(monkeypatch)

    with pytest.raises(HTTPException) as error:
        await require_api_principal(credentials, _request())

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_security_configuration_rejects_duplicate_tokens(monkeypatch):
    monkeypatch.setenv(
        "API_ACCESS_TOKENS",
        json.dumps({"first-user": VALID_TOKEN, "second-user": VALID_TOKEN}),
    )

    with pytest.raises(RuntimeError, match="exactly one owner"):
        validate_api_security_configuration()


def test_costly_and_mutating_routes_declare_bearer_authentication():
    from app.main import app

    openapi = app.openapi()
    protected_operations = (
        ("/collector/collection-jobs/{job_id}/retry", "post"),
        ("/collector/search-datasets", "post"),
        ("/collector/repository-candidates/{candidate_id}/classify", "post"),
        ("/collector/collection-jobs/{job_id}", "get"),
    )

    for path, method in protected_operations:
        assert openapi["paths"][path][method]["security"] == [{"HTTPBearer": []}]


def test_security_configuration_requires_access_tokens(monkeypatch):
    monkeypatch.delenv("API_ACCESS_TOKENS", raising=False)

    with pytest.raises(RuntimeError, match="API_ACCESS_TOKENS"):
        validate_api_security_configuration()


async def test_api_quota_returns_retry_after_when_limit_is_exhausted(monkeypatch):
    async def reject_request(owner_id, operation, *, limit):
        assert owner_id == "test-user"
        assert operation == "repository_search"
        assert limit == 10
        return APIQuotaDecision(
            allowed=False,
            request_count=10,
            retry_after_seconds=17,
        )

    monkeypatch.setattr("app.security.consume_api_quota", reject_request)

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
