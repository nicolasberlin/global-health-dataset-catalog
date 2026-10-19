from __future__ import annotations

import asyncio
import threading
from uuid import uuid4

import pytest
from app.db.connection import _fetchall, _require_database_pool
from app.workers import classification as classification_worker
from helpers.workflows import candidate, headers
from helpers.workflows import classification_decision as decision
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio


async def wait_for_status(database, item, status, owner="alice"):
    async def poll():
        while True:
            stored = await database.get_repository_candidate(item["id"], owner)
            if stored["classification_status"] == status:
                return stored
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=5)


async def test_requested_state_survives_restart_but_discoveries_are_not_executed(
    database, monkeypatch
):
    from app.main import app, lifespan

    await database.init_database()
    discovered = await candidate(database)
    interrupted = await candidate(database)
    await database.enqueue_candidate_classification(interrupted["id"], "alice")
    await database.claim_candidate_classification()
    queued = await candidate(database, query="complete original query")
    await database.enqueue_candidate_classification(queued["id"], "alice")
    await database.close_database_pool()
    calls = []

    def classify(item):
        calls.append((item["id"], item["owner_id"], item["search_query"]))
        return decision(False)

    monkeypatch.setattr(classification_worker, "_classify", classify)
    monkeypatch.setenv("API_AUTH_MODE", "local")
    try:
        async with lifespan(app):
            await wait_for_status(database, queued, "rejected")
            assert (await database.get_repository_candidate(discovered["id"], "alice"))[
                "classification_status"
            ] == "pending"
            assert (await database.get_repository_candidate(interrupted["id"], "alice"))[
                "classification_status"
            ] == "error"
            assert calls == [(queued["id"], "alice", "complete original query")]
    finally:
        await database.open_database_pool()


async def test_concurrent_requests_and_claims_create_one_execution(database):
    await database.init_database()
    item = await candidate(database)
    requests = await asyncio.gather(
        *(database.enqueue_candidate_classification(item["id"], "alice") for _ in range(4))
    )
    assert sum(result is not None for result in requests) == 1
    claims = await asyncio.gather(*(database.claim_candidate_classification() for _ in range(4)))
    assert sum(result is not None for result in claims) == 1
    assert next(result for result in claims if result)["owner_id"] == "alice"
    assert await database.enqueue_candidate_classification(item["id"], "bob", retry=True) is None


async def test_worker_completes_after_http_client_closes_and_preserves_atomic_collection(
    database, api, monkeypatch
):
    await database.init_database()
    item = await candidate(database)
    calls = []

    def classify(stored):
        calls.append(stored["id"])
        return decision()

    monkeypatch.setattr(classification_worker, "_classify", classify)
    path = f"/collector/repository-candidates/{item['id']}"
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        posted = await client.post(f"{path}/classify", headers=headers())
        assert posted.status_code == 202
        assert posted.json()["classification_status"] == "queued"
        assert calls == []
        repeat = await client.post(f"{path}/classify", headers=headers())
        assert repeat.status_code == 202
    # No HTTP client/request is alive when the persisted request is executed.
    async with classification_worker.classification_workers(concurrency=1, poll_interval=0.01):
        await wait_for_status(database, item, "accepted")
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        read = await client.get(path, headers=headers())
        repeated = await client.post(f"{path}/classify?retry=true", headers=headers())
        assert read.status_code == repeated.status_code == 200
        assert read.json() == repeated.json()
        assert read.json()["automatic_collection"]["job"]["status"] == "pending"
    assert calls == [item["id"]]
    async with _require_database_pool().connection() as connection:
        quotas = await _fetchall(connection, "SELECT request_count FROM api_rate_limits")
    assert quotas == [{"request_count": 1}]


@pytest.mark.parametrize("stage", ["llm", "no_decision", "persistence"])
async def test_worker_failure_is_stored_and_only_explicit_retry_queues_again(
    database, api, monkeypatch, stage
):
    await database.init_database()
    item = await candidate(database)
    await database.enqueue_candidate_classification(item["id"], "alice")

    def classify(stored):
        if stage == "llm":
            raise RuntimeError("private-provider-diagnostic")
        return None if stage == "no_decision" else decision()

    async def fail_persistence(*args, **kwargs):
        raise RuntimeError("private-database-diagnostic")

    monkeypatch.setattr(classification_worker, "_classify", classify)
    if stage == "persistence":
        monkeypatch.setattr(
            classification_worker, "complete_candidate_classification", fail_persistence
        )
    async with classification_worker.classification_workers(concurrency=1, poll_interval=0.01):
        await wait_for_status(database, item, "error")
    path = f"/collector/repository-candidates/{item['id']}"
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        failed = await client.get(path, headers=headers())
        assert failed.json()["classification_error"] == "Candidate classification failed."
        assert "private-" not in failed.text
        assert (await client.post(f"{path}/classify", headers=headers())).status_code == 409
        assert (
            await client.post(f"{path}/classify?retry=true", headers=headers("bob"))
        ).status_code == 404
        retried = await client.post(f"{path}/classify?retry=true", headers=headers())
        assert retried.status_code == 202
        assert retried.json()["classification_status"] == "queued"


async def test_reads_and_recovery_are_scoped_to_owner_and_never_schedule(database, api):
    await database.init_database()
    first = await candidate(database)
    latest = await candidate(database, query="latest alice search")
    bob = await candidate(database, "bob", query="private bob query")
    await database.enqueue_candidate_classification(latest["id"], "alice")
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.get("/collector/repository-analyses/latest")).status_code == 401
        restored = await client.get("/collector/repository-analyses/latest", headers=headers())
        assert restored.json()["query"] == "latest alice search"
        assert [item["candidate_id"] for item in restored.json()["items"]] == [str(latest["id"])]
        forbidden = await client.get(
            f"/collector/repository-candidates/{bob['id']}", headers=headers()
        )
        missing = await client.get(f"/collector/repository-candidates/{uuid4()}", headers=headers())
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()
    assert (await database.get_repository_candidate(first["id"], "alice"))[
        "classification_status"
    ] == "pending"
    assert (await database.get_repository_candidate(bob["id"], "bob"))[
        "classification_status"
    ] == "pending"


async def test_classification_capacity_is_bounded_and_shutdown_keeps_backlog(database, monkeypatch):
    await database.init_database()
    items = [await candidate(database) for _ in range(3)]
    for item in items:
        await database.enqueue_candidate_classification(item["id"], "alice")
    release = threading.Event()
    entered = []

    def classify(item):
        entered.append(item["id"])
        assert release.wait(timeout=5)
        return decision(False)

    monkeypatch.setattr(classification_worker, "_classify", classify)
    manager = classification_worker.classification_workers(concurrency=1, poll_interval=0.01)
    await manager.__aenter__()
    closing = None
    try:
        await wait_for_status(database, items[0], "classifying")
        assert (await database.get_repository_candidate(items[1]["id"], "alice"))[
            "classification_status"
        ] == "queued"
        closing = asyncio.create_task(manager.__aexit__(None, None, None))
        await asyncio.sleep(0)
        assert not closing.done()
    finally:
        release.set()
        if closing is None:
            closing = asyncio.create_task(manager.__aexit__(None, None, None))
        await asyncio.wait_for(closing, timeout=5)
    assert entered == [items[0]["id"]]
    assert (await database.get_repository_candidate(items[0]["id"], "alice"))[
        "classification_status"
    ] == "rejected"
    assert (await database.get_repository_candidate(items[2]["id"], "alice"))[
        "classification_status"
    ] == "queued"


async def test_reinitialization_preserves_candidates_and_queued_classification(database):
    await database.init_database()
    item = await candidate(database)
    queued = await database.enqueue_candidate_classification(item["id"], "alice")
    assert queued["classification_status"] == "queued"

    await database.init_database()
    await database.init_database()

    stored = await database.get_repository_candidate(item["id"], "alice")
    assert stored["title"] == "Mortality"
    assert stored["classification_status"] == "queued"
    assert await database.get_repository_candidate(item["id"], "bob") is None
    claimed = await database.claim_candidate_classification()
    assert claimed["id"] == item["id"]
    assert claimed["classification_status"] == "classifying"
    assert await database.claim_candidate_classification() is None
