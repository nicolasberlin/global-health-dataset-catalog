"""Readiness is bounded, recoverable and independent of cheap liveness."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from app import main
from app.db import connection as db
from httpx import ASGITransport, AsyncClient
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from collector.classification import factory

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(main.app.state, "ready", True, raising=False)
    for _, model_var, _, key_var in factory._DEFAULT_VOTERS:
        monkeypatch.setenv(key_var, "private-test-key")
        monkeypatch.delenv(model_var, raising=False)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        yield c


@pytest.fixture
def pool(monkeypatch):
    conn = Mock()
    conn.close = AsyncMock()
    conn.execute = AsyncMock(return_value=Mock(fetchone=AsyncMock(return_value={"ready": 1})))
    released = Mock()

    @asynccontextmanager
    async def acquire(*, timeout):
        assert 0 < timeout <= 2
        try:
            yield conn
        finally:
            released()

    pool = Mock(connection=Mock(side_effect=acquire), conn=conn, released=released)
    monkeypatch.setattr(db, "_database_pool", pool)
    monkeypatch.setattr(db, "_initialized_pool", pool)
    return pool


async def test_success_reuses_pool_and_does_not_initialize_or_call_models(
    client, pool, monkeypatch,
):
    initialize = AsyncMock(side_effect=AssertionError("Must not migrate during probes"))
    create_client = Mock(side_effect=AssertionError("Must not construct an LLM client"))
    monkeypatch.setattr(main, "init_database", initialize)
    monkeypatch.setattr(factory, "HTTPJSONLLMClient", create_client)
    for _ in range(2):
        response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["cache-control"] == "no-store"
    assert pool.connection.call_count == pool.released.call_count == 2
    assert all(call.args[0] == "SELECT 1 AS ready" for call in pool.conn.execute.call_args_list)
    initialize.assert_not_awaited()
    create_client.assert_not_called()


@pytest.mark.parametrize("state", ["starting", "no_pool", "not_initialized", "old_pool"])
async def test_uninitialized_state_is_unavailable(client, pool, monkeypatch, state):
    if state == "starting":
        monkeypatch.setattr(main.app.state, "ready", False)
    elif state == "no_pool":
        monkeypatch.setattr(db, "_database_pool", None)
    else:
        monkeypatch.setattr(db, "_initialized_pool", None if state == "not_initialized" else Mock())
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    pool.connection.assert_not_called()


async def test_missing_configuration_recovers_without_database_or_provider_calls(
    client, pool, monkeypatch,
):
    variable = factory._DEFAULT_VOTERS[0][3]
    monkeypatch.delenv(variable)
    assert (await client.get("/ready")).status_code == 503
    pool.connection.assert_not_called()
    monkeypatch.setenv(variable, "restored-key")
    assert (await client.get("/ready")).status_code == 200


@pytest.mark.parametrize("failure", [OperationalError, PoolTimeout, RuntimeError])
async def test_database_errors_are_secret_free_and_recover(client, pool, caplog, failure):
    secret = "postgresql://private-user:private-password@private-host/db?secret=private-test-key"
    pool.conn.execute.side_effect = failure(secret)
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "private" not in response.text + str(response.headers) + caplog.text
    pool.conn.execute.side_effect = None
    assert (await client.get("/ready")).status_code == 200
    assert pool.released.call_count == 2


async def test_acquisition_timeout_and_recovery(client, pool):
    acquire = pool.connection.side_effect

    @asynccontextmanager
    async def exhausted(*, timeout):
        raise PoolTimeout("private-database-details")
        yield  # pragma: no cover - context-manager protocol

    pool.connection.side_effect = exhausted
    assert (await client.get("/ready")).status_code == 503
    pool.conn.execute.assert_not_awaited()
    pool.connection.side_effect = acquire
    assert (await client.get("/ready")).status_code == 200


async def test_total_budget_includes_acquisition_and_closes_before_cancellation(
    client, pool, monkeypatch,
):
    monkeypatch.setattr(db, "READINESS_TIMEOUT_SECONDS", 0.15)
    acquire = pool.connection.side_effect
    cancelled = asyncio.Event()
    wait = asyncio.wait
    budgets = []

    async def record_budget(tasks, *, timeout):
        budgets.append(timeout)
        return await wait(tasks, timeout=timeout)

    monkeypatch.setattr(db.asyncio, "wait", record_budget)

    @asynccontextmanager
    async def slow_acquisition(*, timeout):
        await asyncio.sleep(0.10)
        async with acquire(timeout=timeout) as conn:
            yield conn

    async def stalled_query(*args):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # An open psycopg connection can attempt a slow server-side cancel.
            assert pool.conn.close.await_count == 1
            cancelled.set()
            raise

    pool.connection.side_effect = slow_acquisition
    pool.conn.execute.side_effect = stalled_query
    started = asyncio.get_running_loop().time()
    response = await client.get("/ready")
    elapsed = asyncio.get_running_loop().time() - started
    assert response.status_code == 503
    assert 0.13 <= elapsed < 0.5
    assert budgets[0] <= 0.06  # Acquisition has already consumed most of the budget.
    assert cancelled.is_set()
    pool.released.assert_called_once()
    pool.conn.execute.side_effect = None
    pool.connection.side_effect = acquire
    assert (await client.get("/ready")).status_code == 200


async def test_request_cancellation_releases_connection(client, pool):
    started = asyncio.Event()

    async def stalled_query(*args):
        started.set()
        await asyncio.Event().wait()

    pool.conn.execute.side_effect = stalled_query
    request = asyncio.create_task(client.get("/ready"))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    pool.conn.close.assert_awaited_once()
    pool.released.assert_called_once()


async def test_shutdown_during_probe_is_unavailable(client, pool, monkeypatch):
    async def finish_shutdown(*args):
        monkeypatch.setattr(main.app.state, "ready", False)
        return Mock(fetchone=AsyncMock(return_value={"ready": 1}))

    pool.conn.execute.side_effect = finish_shutdown
    assert (await client.get("/ready")).status_code == 503


async def test_pool_replaced_during_probe_is_unavailable(client, pool, monkeypatch):
    async def reopen(*args):
        replacement = Mock()
        monkeypatch.setattr(db, "_database_pool", replacement)
        monkeypatch.setattr(db, "_initialized_pool", replacement)
        return Mock(fetchone=AsyncMock(return_value={"ready": 1}))

    pool.conn.execute.side_effect = reopen
    assert (await client.get("/ready")).status_code == 503


async def test_health_never_checks_database_or_model_configuration(client, monkeypatch):
    probe = AsyncMock(side_effect=AssertionError("Must not access DB"))
    validate = Mock(side_effect=AssertionError("Must not access model configuration"))
    monkeypatch.setattr(main, "check_database_readiness", probe)
    monkeypatch.setattr(main, "validate_default_classifier_configuration", validate)
    monkeypatch.setattr(main.app.state, "ready", False)
    assert (await client.get("/health")).json() == {"status": "ok"}
    probe.assert_not_awaited()
    validate.assert_not_called()


@pytest.mark.parametrize("fail_startup", [False, True])
async def test_lifespan_marks_ready_only_after_startup_and_before_worker_shutdown(
    client, monkeypatch, fail_startup,
):
    close = AsyncMock()
    monkeypatch.setattr(main, "configure_operational_logging", Mock())
    monkeypatch.setattr(main, "validate_api_security_configuration", Mock())
    monkeypatch.setattr(main, "open_database_pool", AsyncMock())
    monkeypatch.setattr(main, "close_database_pool", close)
    monkeypatch.setattr(main, "check_database_readiness", AsyncMock())

    async def startup_step():
        assert (await client.get("/ready")).status_code == 503
        if fail_startup:
            raise RuntimeError("failed initialization")

    for name in ("init_database", "mark_interrupted_votes_error",
                 "mark_interrupted_search_sessions_error",
                 "mark_interrupted_candidate_classifications_error",
                 "mark_interrupted_collection_jobs_error"):
        monkeypatch.setattr(main, name, startup_step)

    @asynccontextmanager
    async def workers():
        assert not main.app.state.ready
        try:
            yield
        finally:
            assert (await client.get("/ready")).status_code == 503

    monkeypatch.setattr(main, "collection_workers", workers)
    monkeypatch.setattr(main, "classification_workers", workers)
    if fail_startup:
        with pytest.raises(RuntimeError, match="failed initialization"):
            async with main.lifespan(main.app):
                pytest.fail("Failed startup must not serve requests")
    else:
        async with main.lifespan(main.app):
            assert (await client.get("/ready")).status_code == 200
    assert not main.app.state.ready
    close.assert_awaited_once()


async def test_real_database_initialization_exhaustion_and_recovery(database, client, monkeypatch):
    assert (await client.get("/ready")).status_code == 503
    await database.init_database()
    assert (await client.get("/ready")).status_code == 200
    pool = db._require_database_pool()
    held = []
    try:
        for _ in range(pool.max_size):
            held.append(await pool.getconn(timeout=3))
        monkeypatch.setattr(db, "READINESS_TIMEOUT_SECONDS", 0.05)
        assert (await client.get("/ready")).status_code == 503
        assert (await client.get("/health")).status_code == 200
    finally:
        for conn in held:
            await pool.putconn(conn)
    assert (await client.get("/ready")).status_code == 200
    await database.close_database_pool()
    await database.open_database_pool()
    assert (await client.get("/ready")).status_code == 503
    await database.init_database()
    assert (await client.get("/ready")).status_code == 200


async def test_real_stalled_query_is_discarded_and_recovers(database, client, monkeypatch):
    await database.init_database()
    monkeypatch.setattr(db, "READINESS_TIMEOUT_SECONDS", 0.05)
    fetchone = db._fetchone
    closed = []

    async def stalled(connection, sql):
        closed.append(connection)
        return await fetchone(connection, "SELECT pg_sleep(10)")

    monkeypatch.setattr(db, "_fetchone", stalled)
    started = asyncio.get_running_loop().time()
    assert (await client.get("/ready")).status_code == 503
    assert asyncio.get_running_loop().time() - started < 0.5
    assert closed[0].closed
    monkeypatch.setattr(db, "_fetchone", fetchone)
    monkeypatch.setattr(db, "READINESS_TIMEOUT_SECONDS", 2)
    assert (await client.get("/ready")).status_code == 200
