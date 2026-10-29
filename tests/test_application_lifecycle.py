"""Runtime ownership and worker degradation stop admission without exposing errors."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from app import lifecycle, main
from app.workers.runtime import persisted_workers
from httpx import ASGITransport, AsyncClient
from psycopg.errors import DiskFull

pytestmark = pytest.mark.anyio


@pytest.fixture
async def runtime(monkeypatch):
    ownership = Mock(healthy=True, lost=asyncio.Event(), activate=AsyncMock())
    monkeypatch.setattr(main.app.state, "ready", True, raising=False)
    monkeypatch.setattr(main.app.state, "runtime_enforced", True, raising=False)
    monkeypatch.setattr(main.app.state, "ownership", ownership, raising=False)
    monkeypatch.setattr(main, "validate_default_classifier_configuration", Mock())
    monkeypatch.setattr(main, "check_database_readiness", AsyncMock())
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        yield client, ownership


async def test_worker_failure_is_unavailable_and_recovers(runtime, monkeypatch):
    client, _ = runtime
    monkeypatch.setattr(main, "workers_ready", lambda: False)
    assert (await client.get("/ready")).status_code == 503
    main.check_database_readiness.assert_not_awaited()
    monkeypatch.setattr(main, "workers_ready", lambda: True)
    assert (await client.get("/ready")).status_code == 200


async def test_acquisition_failure_blocks_admission_and_same_consumer_recovers(runtime):
    client, _ = runtime
    failed_polls, repaired = asyncio.Event(), asyncio.Event()
    empty_poll, publish_job, executed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    consumer_tasks = set()
    failures = 0
    dispatched = False

    async def claim(*, claim_token):
        nonlocal failures, dispatched
        consumer_tasks.add(asyncio.current_task())
        if not repaired.is_set():
            failures += 1
            if failures >= 3:
                failed_polls.set()
            raise DiskFull("Simulated acquisition storage failure.")
        if not publish_job.is_set():
            empty_poll.set()
            return None
        if not dispatched:
            dispatched = True
            return {"id": 1}
        return None

    execute = AsyncMock(side_effect=lambda *_: executed.set())
    async with persisted_workers(
        claim=claim, execute=execute, concurrency=1, name="search", poll_interval=.001,
    ):
        await asyncio.wait_for(failed_polls.wait(), 1)
        assert (await client.get("/ready")).status_code == 503
        main.check_database_readiness.assert_not_awaited()
        response = await client.post("/collector/searches", json={"query": "malaria"})
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert (await client.get("/health")).status_code == 200
        execute.assert_not_awaited()

        repaired.set()
        await asyncio.wait_for(empty_poll.wait(), 1)
        assert (await client.get("/ready")).status_code == 200
        execute.assert_not_awaited()

        publish_job.set()
        await asyncio.wait_for(executed.wait(), 1)
        execute.assert_awaited_once()
        assert execute.await_args.args[0] == {"id": 1}
        assert len(consumer_tasks) == 1


async def test_readiness_rechecks_workers_after_database_probe(runtime, monkeypatch):
    client, _ = runtime
    healthy = True
    monkeypatch.setattr(main, "workers_ready", lambda: healthy)

    async def degrade():
        nonlocal healthy
        healthy = False

    main.check_database_readiness.side_effect = degrade
    assert (await client.get("/ready")).status_code == 503


async def test_readiness_rechecks_ownership_after_database_probe(runtime):
    client, ownership = runtime

    async def lose():
        ownership.healthy = False

    main.check_database_readiness.side_effect = lose
    assert (await client.get("/ready")).status_code == 503


async def test_lost_ownership_rejects_commands_and_keeps_liveness(runtime):
    client, ownership = runtime
    ownership.healthy = False
    response = await client.post("/collector/searches", json={"query": "malaria"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.headers["cache-control"] == "no-store"
    assert (await client.get("/health")).status_code == 200


async def test_lock_monitor_fences_workers_on_loss(runtime, monkeypatch):
    _, ownership = runtime
    stop = Mock()
    monkeypatch.setattr(lifecycle, "request_worker_stop", stop)
    watcher = asyncio.create_task(lifecycle._watch_ownership(main.app, ownership))
    ownership.lost.set()
    await asyncio.wait_for(watcher, timeout=1)
    assert not main.app.state.ready
    stop.assert_called_once_with(force=True)


async def test_explicit_migration_mode_verifies_without_ddl(monkeypatch):
    monkeypatch.setenv("DATABASE_MIGRATE_ON_STARTUP", "false")
    monkeypatch.setattr(main.app.state, "ready", False, raising=False)
    monkeypatch.setattr(main.app.state, "runtime_enforced", False, raising=False)
    monkeypatch.setattr(main.app.state, "ownership", None, raising=False)
    ownership = Mock(healthy=True, lost=asyncio.Event(), activate=AsyncMock())

    @asynccontextmanager
    async def lock():
        yield ownership

    @asynccontextmanager
    async def group():
        yield

    monkeypatch.setattr(lifecycle, "application_lock", lock)
    for name in ("configure_operational_logging", "validate_api_security_configuration"):
        monkeypatch.setattr(lifecycle, name, Mock())
    for name in ("open_database_pool", "close_database_pool", "init_database",
                 "validate_database_schema", "mark_interrupted_votes_error",
                 "mark_interrupted_search_sessions_error",
                 "mark_interrupted_candidate_classifications_error",
                 "mark_interrupted_collection_jobs_error"):
        monkeypatch.setattr(lifecycle, name, AsyncMock())
    for name in ("collection_workers", "classification_workers", "search_workers"):
        monkeypatch.setattr(lifecycle, name, group)
    async with lifecycle.lifespan(main.app):
        lifecycle.validate_database_schema.assert_awaited_once()
        lifecycle.init_database.assert_not_awaited()
        ownership.activate.assert_awaited_once()
    assert not main.app.state.ready


async def test_startup_activates_generation_then_recovers_parents_before_votes(monkeypatch):
    events = []
    ownership = Mock(healthy=True, lost=asyncio.Event(), activate=AsyncMock(
        side_effect=lambda: events.append("activate"),
    ))

    @asynccontextmanager
    async def lock():
        yield ownership

    @asynccontextmanager
    async def group():
        assert events == ["activate", "search", "classification", "collection", "votes"]
        yield

    monkeypatch.setattr(main.app.state, "ready", False, raising=False)
    monkeypatch.setattr(main.app.state, "runtime_enforced", False, raising=False)
    monkeypatch.setattr(main.app.state, "ownership", None, raising=False)
    monkeypatch.setattr(lifecycle, "application_lock", lock)
    for name in ("configure_operational_logging", "validate_api_security_configuration"):
        monkeypatch.setattr(lifecycle, name, Mock())
    for name in ("open_database_pool", "close_database_pool", "init_database",
                 "validate_database_schema"):
        monkeypatch.setattr(lifecycle, name, AsyncMock())
    for name, event in (
        ("mark_interrupted_search_sessions_error", "search"),
        ("mark_interrupted_candidate_classifications_error", "classification"),
        ("mark_interrupted_collection_jobs_error", "collection"),
        ("mark_interrupted_votes_error", "votes"),
    ):
        monkeypatch.setattr(
            lifecycle, name, AsyncMock(side_effect=lambda event=event: events.append(event)),
        )
    for name in ("collection_workers", "classification_workers", "search_workers"):
        monkeypatch.setattr(lifecycle, name, group)
    async with lifecycle.lifespan(main.app):
        assert main.app.state.ready


async def test_cancelled_readiness_request_does_not_release_ownership(runtime):
    client, ownership = runtime
    entered = asyncio.Event()

    async def stalled():
        entered.set()
        await asyncio.Event().wait()

    main.check_database_readiness.side_effect = stalled
    request = asyncio.create_task(client.get("/ready"))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert ownership.healthy
    assert not ownership.lost.is_set()
    ownership.check.assert_not_called()
