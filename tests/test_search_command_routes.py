"""Search commands enforce durable admission and public contracts."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.api import search_progress as progress_reads
from app.api import searches
from app.api.router import router
from app.db.connection import _fetchall, _require_database_pool
from app.db.execution.commands import CommandConflict
from app.policies.quotas import QuotaExceeded
from fastapi import FastAPI
from helpers.access import inject_owners
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def command_api(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    commands = {}
    calls = []

    async def admit(owner, key, *, query, access_mode, client_key):
        calls.append((owner, key, query, access_mode, client_key))
        if key in commands:
            if commands[key]["query"] != query:
                raise CommandConflict("Command payload conflicts with the original request.")
            return commands[key], True
        row = {
            "id": uuid4(),
            "query": query,
            "status": "queued",
            "origin": "database",
            "attempt_number": 1,
            "errors": [],
            "warnings": [],
            "local_dataset_ids": [],
        }
        commands[key] = row
        return row, False

    async def progress(search_id, owner):
        assert owner == "alice"
        row = next((row for row in commands.values() if row["id"] == search_id), None)
        return (row, [], {}) if row else None

    def forbidden(*args):
        pytest.fail("HTTP route must never call a discovery provider")

    monkeypatch.setattr(searches, "admit_search", admit)
    monkeypatch.setattr(progress_reads, "read_search_progress", progress)
    monkeypatch.setattr("app.workers.search.worker.search_repository_metadata", forbidden)
    app = FastAPI()
    app.include_router(router)
    return inject_owners(app), calls


def headers(key=None):
    return {"X-Test-Owner": "alice", **({"Idempotency-Key": key} if key else {})}


async def test_removed_search_datasets_route_is_unavailable(command_api):
    app, calls = command_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/collector/search-datasets", json={"query": "health"}, headers=headers("removed")
        )
    assert response.status_code == 404
    assert "/collector/search-datasets" not in app.openapi()["paths"]
    assert not calls


async def test_same_key_replays_without_new_search(command_api):
    app, calls = command_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/collector/searches", json={"query": "health"}, headers=headers("same")
        )
        replay = await client.post(
            "/collector/searches", json={"query": "health"}, headers=headers("same")
        )
        conflict = await client.post(
            "/collector/searches", json={"query": "other"}, headers=headers("same")
        )
    assert first.status_code == 202 and replay.status_code == 200
    assert first.json() == replay.json() and first.headers["location"] == replay.headers["location"]
    assert conflict.status_code == 409 and len(calls) == 3


async def test_search_preserves_authentication_and_transactional_quota_errors(
    command_api, monkeypatch
):
    app, calls = command_api

    async def full(*args, **kwargs):
        calls.append("quota")
        raise QuotaExceeded(17, "The search queue is full.")

    monkeypatch.setattr(searches, "admit_search", full)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.post(
            "/collector/searches", json={"query": "health"}, headers={"Idempotency-Key": "command"}
        )
        assert unauthorized.status_code == 401 and not calls
        rejected = await client.post(
            "/collector/searches", json={"query": "health"}, headers=headers("command")
        )
    assert rejected.status_code == 429 and rejected.headers["retry-after"] == "17"
    assert calls == ["quota"] and "location" not in rejected.headers


async def test_search_requires_key_and_rejects_browser_authority(command_api):
    app, calls = command_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(
            "/collector/searches", json={"query": "health"}, headers=headers()
        )
        assert missing.status_code == 422
        for extra in ({"owner_id": "bob"}, {"client_key": "forged"}, {"access_mode": "local"}):
            invalid = await client.post(
                "/collector/searches", json={"query": "health", **extra}, headers=headers("command")
            )
            assert invalid.status_code == 422
        blank = await client.post(
            "/collector/searches", json={"query": "   "}, headers=headers("command")
        )
        assert blank.status_code == 400
    assert not calls


async def test_concurrent_searches_share_atomic_queue_capacity(database, monkeypatch):
    await database.init_database()
    monkeypatch.setenv("API_AUTH_MODE", "local")
    monkeypatch.setenv("SEARCH_MAX_ACTIVE", "1")
    app = FastAPI()
    app.include_router(router)
    inject_owners(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/collector/searches", json={"query": "health"}, headers=headers(f"key-{index}")
                )
                for index in range(2)
            ]
        )
        assert sorted(response.status_code for response in responses) == [202, 429]
        accepted_index = next(
            i for i, response in enumerate(responses) if response.status_code == 202
        )
        replay = await client.post(
            "/collector/searches",
            json={"query": "health"},
            headers=headers(f"key-{accepted_index}"),
        )
        assert replay.status_code == 200
        assert replay.json() == responses[accepted_index].json()
    async with _require_database_pool().connection() as connection:
        states = await _fetchall(connection, "SELECT status, execution_mode FROM search_sessions")
        receipts = await _fetchall(connection, "SELECT command_key FROM api_commands")
        quotas = await _fetchall(connection, "SELECT request_count FROM api_rate_limits")
    assert states == [{"status": "queued", "execution_mode": "worker"}]
    assert len(receipts) == 1 and quotas == [{"request_count": 1}]
