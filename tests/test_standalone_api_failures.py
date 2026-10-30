"""Failure/recovery contracts for an API consumer without any frontend process."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.db.connection import _fetchall, _require_database_pool
from app.db.search import jobs as search_jobs
from app.workers.search import workers as search_worker
from helpers.workflows import candidate_for, decision, headers
from httpx import ASGITransport, AsyncClient

from collector.repository_search import RepositorySearchResponse

pytestmark = pytest.mark.anyio


def client_for(application):
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


async def sql(query, parameters=None):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, query, parameters)


async def persisted_state():
    tables = (
        "search_sessions", "repository_candidates", "collection_jobs", "api_commands",
        "api_rate_limits", "collected_datasets", "classification_runs",
    )
    return {
        table: sorted(await sql(f"SELECT * FROM {table}"), key=repr)
        for table in tables
    }


async def accepted_candidate(database):
    item = await candidate_for(database)
    await database.complete_search_session(item["search_session_id"], "alice", origin="online")
    completed = await database.complete_candidate_classification(item["id"], "alice", decision())
    return item, completed.collection.job


async def test_full_queue_rejects_without_receipt_and_replay_survives_pool_restart(
    database, api, monkeypatch,
):
    await database.init_database()
    monkeypatch.setenv("SEARCH_MAX_ACTIVE", "1")
    monkeypatch.setattr(
        search_worker, "search_repository_metadata", lambda _: RepositorySearchResponse()
    )
    alice = {**headers(), "Idempotency-Key": "accepted-command"}
    bob = {**headers("bob"), "Idempotency-Key": "initially-refused"}
    async with client_for(api) as client:
        first = await client.post("/collector/searches", headers=alice, json={"query": "malaria"})
        assert first.status_code == 202
        refused = await client.post("/collector/searches", headers=bob, json={"query": "diabetes"})
        assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
        assert len(await sql("SELECT * FROM api_commands")) == 1
        assert await sql("SELECT owner_id FROM api_rate_limits") == [{"owner_id": "alice"}]
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    async with client_for(api) as client:
        replays = await asyncio.gather(*[
            client.post("/collector/searches", headers=alice, json={"query": "malaria"})
            for _ in range(4)
        ])
        assert all(response.status_code == 200 for response in replays)
        assert all(
            response.json()["search_id"] == first.json()["search_id"] for response in replays
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            await search_worker.SearchWorker().execute(await search_jobs.claim_search(), executor)
        admitted = await client.post(
            "/collector/searches", headers=bob, json={"query": "diabetes"}
        )
        assert admitted.status_code == 202
        finished = await client.get(first.headers["location"], headers=headers())
        assert finished.json()["execution_status"] == "finished"
        assert finished.json()["outcome"] == "empty"
    assert len(await sql("SELECT * FROM api_commands")) == 2
    assert await sql("SELECT request_count FROM api_rate_limits ORDER BY owner_id") == [
        {"request_count": 1}, {"request_count": 1},
    ]
