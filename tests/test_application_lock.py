"""Application ownership is exclusive, schema-scoped, and never silently regained."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from app.db.execution import application_lock as locking

pytestmark = pytest.mark.anyio


async def test_second_instance_cannot_run_recovery_or_migrations(database):
    async with locking.application_lock() as owner:
        assert owner.healthy
        await owner.check()
        with pytest.raises(locking.ApplicationAlreadyRunning):
            async with locking.application_lock():
                pytest.fail("Second instance must not enter its startup body")
        assert owner.healthy
    async with locking.application_lock() as replacement:
        await replacement.check()


async def test_released_lock_is_detected_and_never_reacquired(database):
    async with locking.application_lock(probe_interval=60) as owner:
        await owner.connection.execute("SELECT pg_advisory_unlock(%s)", (owner.key,))
        with pytest.raises(locking.ApplicationLockLost):
            await owner.check()
        assert owner.lost.is_set() and not owner.healthy
        async with locking.application_lock() as replacement:
            assert replacement.healthy
            with pytest.raises(locking.ApplicationLockLost):
                owner.require_held()


async def test_background_monitor_detects_loss_without_a_request_probe(database):
    async with locking.application_lock(probe_interval=.01) as owner:
        await owner.connection.execute("SELECT pg_advisory_unlock(%s)", (owner.key,))
        await asyncio.wait_for(owner.lost.wait(), 1)
        assert not owner.healthy
        with pytest.raises(locking.ApplicationLockLost):
            owner.require_held()


async def test_cancelled_worker_does_not_release_application_lock(database, monkeypatch):
    from app.workers import runtime as workers

    started = asyncio.Event()

    async def pending_claim(*, claim_token):
        started.set()
        await asyncio.Event().wait()

    async with locking.application_lock() as owner:
        manager = workers.persisted_workers(
            claim=pending_claim, execute=AsyncMock(), concurrency=1, name="search",
            shutdown_timeout=.01,
        )
        await manager.__aenter__()
        await started.wait()
        await manager.__aexit__(None, None, None)
        assert owner.healthy and not owner.lost.is_set()
        with pytest.raises(locking.ApplicationAlreadyRunning):
            async with locking.application_lock():
                pytest.fail("Worker cancellation must not release the application owner's session")


async def test_lock_connection_is_dedicated_and_does_not_exhaust_single_slot_pool(database):
    from app.db.connection import _require_database_pool

    pool = _require_database_pool()
    held = [await pool.getconn(timeout=1) for _ in range(pool.max_size)]
    try:
        async with locking.application_lock() as owner:
            await owner.check()
    finally:
        for connection in held:
            await pool.putconn(connection)


async def test_lock_probe_timeout_closes_session_and_marks_unavailable(monkeypatch):
    connection = Mock(closed=False)
    connection.close = AsyncMock()
    owner = locking.ApplicationOwnership(connection, 123, probe_timeout=.01)
    async def pending():
        await asyncio.Event().wait()

    async def query(*args):
        return await pending()

    monkeypatch.setattr(locking, "_fetchone", query)
    with pytest.raises(locking.ApplicationLockLost):
        await asyncio.wait_for(owner.check(), .2)
    assert owner.lost.is_set() and not owner.healthy
    assert connection.close.await_count >= 1


async def test_cancelled_monitor_probe_does_not_report_lock_loss(monkeypatch):
    connection = Mock(closed=False)
    connection.close = AsyncMock()
    owner = locking.ApplicationOwnership(connection, 123)
    entered = asyncio.Event()
    events = Mock()

    async def query(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(locking, "_fetchone", query)
    monkeypatch.setattr(locking, "emit_event", events)
    check = asyncio.create_task(owner.check())
    await entered.wait()
    check.cancel()
    with pytest.raises(asyncio.CancelledError):
        await check
    assert not owner.lost.is_set()
    events.assert_not_called()


async def test_activation_is_runtime_only_and_idempotent(database):
    from app.db.connection import _fetchone, _require_database_pool

    await database.init_database()
    async with locking.application_lock() as owner:
        async with _require_database_pool().connection() as connection:
            assert await _fetchone(connection, "SELECT * FROM application_ownership") is None
        await owner.activate()
        generation = owner.generation
        assert generation is not None
        await owner.activate()
        assert owner.generation == generation
        async with _require_database_pool().connection() as connection:
            assert await _fetchone(connection, "SELECT * FROM application_ownership") == {
                "singleton": True, "generation": generation,
            }
    # The explicit migration command also acquires this lock but never activates.
    async with locking.application_lock() as migration_owner:
        await database.init_database()
        assert migration_owner.generation is None
        async with _require_database_pool().connection() as connection:
            assert (await _fetchone(connection, "SELECT * FROM application_ownership"))[
                "generation"
            ] == generation


@pytest.mark.parametrize("activate", [False, True])
async def test_missing_or_inactive_generation_rejects_claim(database, activate):
    from app.db.connection import _require_database_pool
    from app.db.search.jobs import claim_search

    await database.init_database()
    async with locking.application_lock() as owner:
        if activate:
            await owner.activate()
            async with _require_database_pool().connection() as connection:
                await connection.execute("DELETE FROM application_ownership")
        with pytest.raises(locking.ApplicationLockLost):
            await claim_search()
        assert owner.lost.is_set()


async def test_activation_verifies_actual_lock_before_rotating_generation(database):
    from app.db.connection import _fetchone, _require_database_pool

    await database.init_database()
    async with locking.application_lock(probe_interval=60) as owner:
        await owner.connection.execute("SELECT pg_advisory_unlock(%s)", (owner.key,))
        with pytest.raises(locking.ApplicationLockLost):
            await owner.activate()
        assert owner.generation is None
        async with _require_database_pool().connection() as connection:
            assert await _fetchone(connection, "SELECT * FROM application_ownership") is None
