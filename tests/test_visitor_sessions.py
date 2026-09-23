from __future__ import annotations

from typing import Annotated

import pytest
from app.routes.collector import router as collector_router
from app.routes.sessions import router as sessions_router
from app.security import APIPrincipal, require_api_principal, validate_api_security_configuration
from app.visitor_sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    VisitorSessionSettings,
    new_visitor_cookie,
)
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from collector.repository_search import RepositorySearchResult

pytestmark = pytest.mark.anyio

ORIGIN = "https://health.example"
SECRET = "test-only-visitor-session-secret-at-least-32-characters"


@pytest.fixture
def public_api(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "public")
    monkeypatch.setenv("API_SESSION_SECRET", SECRET)
    monkeypatch.setenv("API_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.delenv("API_ACCESS_TOKENS", raising=False)
    validate_api_security_configuration()
    app = FastAPI()
    app.include_router(sessions_router)
    app.include_router(collector_router)

    @app.get("/identity")
    @app.post("/identity")
    async def identity(principal: Annotated[APIPrincipal, Depends(require_api_principal)]):
        return {"owner_id": principal.owner_id}

    return app


def browser(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN)


async def bootstrap(client):
    response = await client.post("/session", headers={"Origin": ORIGIN})
    assert response.status_code == 204
    return response


async def test_cookie_bootstrap_reuses_identity_and_does_not_extend_expiration(public_api):
    async with browser(public_api) as client:
        assert (await client.get("/identity")).status_code == 401
        created = await bootstrap(client)
        assert created.content == b""
        assert created.headers["cache-control"] == "no-store"
        cookie = created.headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/",
                          f"Max-Age={SESSION_MAX_AGE_SECONDS}"):
            assert attribute in cookie
        assert "Domain=" not in cookie
        assert SECRET not in cookie

        first = await client.get("/identity")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        assert first.json()["owner_id"].startswith("visitor:")
        reused = await bootstrap(client)
        assert "set-cookie" not in reused.headers
        assert (await client.get("/identity")).json() == first.json()
        assert (await client.post("/identity", headers={"Origin": ORIGIN})).status_code == 200


async def test_separate_browsers_receive_separate_owners(public_api):
    async with browser(public_api) as alice, browser(public_api) as bob:
        await bootstrap(alice)
        await bootstrap(bob)
        assert (await alice.get("/identity")).json() != (await bob.get("/identity")).json()


@pytest.mark.parametrize("origin", [None, "null", "https://other.example", "http://health.example"])
async def test_foreign_or_missing_origin_cannot_issue_cookies_or_start_work(public_api, origin):
    headers = {} if origin is None else {"Origin": origin}
    async with browser(public_api) as client:
        rejected = await client.post("/session", headers=headers)
        assert rejected.status_code == 403
        assert "set-cookie" not in rejected.headers
        await bootstrap(client)
        rejected = await client.post("/identity", headers=headers)
        assert rejected.status_code == 403


@pytest.mark.parametrize("cookie", [
    "visitor:chosen-by-the-browser",
    "invalid.signature",
    "x" * 513,
    new_visitor_cookie(VisitorSessionSettings(secret="a-different-signing-secret", origin=ORIGIN)),
])
async def test_invalid_cookie_is_rejected_and_only_bootstrap_can_replace_it(public_api, cookie):
    async with browser(public_api) as client:
        headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}", "Origin": ORIGIN}
        response = await client.post("/identity", headers=headers)
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
        replaced = await client.post("/session", headers=headers)
        assert replaced.status_code == 204
        assert "set-cookie" in replaced.headers
        assert (await client.get("/identity")).status_code == 200


async def test_expiration_is_enforced_and_new_session_has_new_owner(public_api, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda _: now)
    async with browser(public_api) as client:
        await bootstrap(client)
        original = (await client.get("/identity")).json()
        now += SESSION_MAX_AGE_SECONDS + 1
        assert (await client.get("/identity")).status_code == 401
        await bootstrap(client)
        renewed = await client.get("/identity")
        assert renewed.status_code == 200
        assert renewed.json() != original


async def test_cookie_is_not_transmitted_over_http(public_api):
    async with browser(public_api) as client:
        await bootstrap(client)
        assert (await client.get("http://health.example/identity")).status_code == 401


async def test_public_mode_does_not_fall_back_from_bearer_to_cookie(public_api):
    async with browser(public_api) as client:
        await bootstrap(client)
        response = await client.get("/identity", headers={"Authorization": "Bearer invalid"})
        assert response.status_code == 401


@pytest.mark.parametrize("mode", ["token", "local"])
async def test_bootstrap_is_unavailable_in_existing_modes(public_api, monkeypatch, mode):
    monkeypatch.setenv("API_AUTH_MODE", mode)
    async with browser(public_api) as client:
        response = await client.post("/session", headers={"Origin": ORIGIN})
        assert response.status_code == 404
        assert "set-cookie" not in response.headers


async def test_default_token_mode_does_not_accept_a_visitor_cookie(public_api, monkeypatch):
    async with browser(public_api) as client:
        await bootstrap(client)
        monkeypatch.delenv("API_AUTH_MODE")
        assert (await client.get("/identity")).status_code == 401
        assert (await client.post("/session", headers={"Origin": ORIGIN})).status_code == 404


@pytest.mark.parametrize(("name", "value"), [
    ("API_SESSION_SECRET", ""),
    ("API_SESSION_SECRET", "short"),
    ("API_SESSION_SECRET", " " + SECRET),
    ("API_PUBLIC_ORIGIN", ""),
    ("API_PUBLIC_ORIGIN", "http://health.example"),
    ("API_PUBLIC_ORIGIN", "https://health.example/path"),
    ("API_PUBLIC_ORIGIN", "https://user@health.example"),
    ("API_PUBLIC_ORIGIN", "https://@health.example"),
    ("API_PUBLIC_ORIGIN", "https://health.example:invalid"),
    ("API_PUBLIC_ORIGIN", "https://health.example\n"),
    ("API_AUTH_MODE", "unknown"),
])
def test_invalid_public_configuration_fails_startup(public_api, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=name):
        validate_api_security_configuration()


async def test_cookie_owner_is_passed_to_existing_collector_access_checks(public_api, monkeypatch):
    recorded_owners = []

    async def read_job(job_id, owner_id):
        recorded_owners.append(owner_id)
        return {"id": job_id, "source_url": "https://example.org/data", "status": "done",
                "saved_count": 0}

    monkeypatch.setattr("app.routes.collector.get_collection_job_for_owner", read_job)
    async with browser(public_api) as client:
        await bootstrap(client)
        owner = (await client.get("/identity")).json()["owner_id"]
        response = await client.get("/collector/collection-jobs/1")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert recorded_owners == [owner]


async def test_anonymous_ownership_is_enforced_by_database(public_api, database):
    await database.init_database()
    async with browser(public_api) as alice, browser(public_api) as bob:
        await bootstrap(alice)
        await bootstrap(bob)
        owner = (await alice.get("/identity")).json()["owner_id"]
        search = await database.create_search_session("mortality", owner)
        items = await database.save_repository_candidates(search["id"], owner, [
            RepositorySearchResult(title="Mortality", url="https://example.org/data",
                                   source="DataCite"),
        ])
        path = f"/collector/repository-candidates/{items[0]['id']}"
        assert (await alice.get(path)).status_code == 200
        assert (await bob.get(path)).status_code == 404
        denied = await bob.post(f"{path}/classify", headers={"Origin": ORIGIN})
        assert denied.status_code == 404
        stored = await database.get_repository_candidate(items[0]["id"], owner)
        assert stored["classification_status"] == "pending"
