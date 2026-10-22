"""SQL deadlines survive connection replacement and leave transactions reusable."""

from __future__ import annotations

import time

import pytest
from app import main
from app.db import connection as db_connection
from app.db import schema as db_schema
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from psycopg.errors import LockNotAvailable, QueryCanceled

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("name,value", [
    ("DATABASE_STATEMENT_TIMEOUT_MS", "0"),
    ("DATABASE_STATEMENT_TIMEOUT_MS", "999"),
    ("DATABASE_STATEMENT_TIMEOUT_MS", "300001"),
    ("DATABASE_STATEMENT_TIMEOUT_MS", "1.5"),
    ("DATABASE_STATEMENT_TIMEOUT_MS", "invalid"),
    ("DATABASE_LOCK_TIMEOUT_MS", "99"),
    ("DATABASE_LOCK_TIMEOUT_MS", "30001"),
    ("DATABASE_LOCK_TIMEOUT_MS", ""),
])
async def test_invalid_database_timeouts_fail_configuration(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        db_connection.configured_database_timeouts()


async def test_database_timeout_defaults_and_lock_order(monkeypatch):
    monkeypatch.delenv("DATABASE_STATEMENT_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("DATABASE_LOCK_TIMEOUT_MS", raising=False)
    assert db_connection.configured_database_timeouts() == (30000, 5000)
    monkeypatch.setenv("DATABASE_STATEMENT_TIMEOUT_MS", "1000")
    with pytest.raises(ValueError, match="must not exceed"):
        db_connection.configured_database_timeouts()


async def configured_pool(database, monkeypatch, *, statement="2000", lock="200"):
    await database.close_database_pool()
    monkeypatch.setenv("DATABASE_STATEMENT_TIMEOUT_MS", statement)
    monkeypatch.setenv("DATABASE_LOCK_TIMEOUT_MS", lock)
    await database.open_database_pool()
    return db_connection._require_database_pool()


async def settings(connection):
    return await db_connection._fetchone(connection, """
        SELECT current_setting('statement_timeout') AS statement,
               current_setting('lock_timeout') AS lock,
               current_schema() AS schema, pg_backend_pid() AS pid
    """)


async def test_pool_configures_deadlines_without_overriding_schema_options(database, monkeypatch):
    pool = await configured_pool(database, monkeypatch)
    async with pool.connection() as connection:
        first = await settings(connection)
        assert first["statement"] == "2s" and first["lock"] == "200ms"
        assert first["schema"].startswith("test_")
        await connection.close()
    async with pool.connection(timeout=3) as connection:
        replacement = await settings(connection)
    assert replacement["pid"] != first["pid"]
    assert {key: replacement[key] for key in ("statement", "lock", "schema")} == {
        key: first[key] for key in ("statement", "lock", "schema")
    }


async def test_migration_deadlines_are_local_and_runtime_generation_starts_empty(
    database, monkeypatch,
):
    pool = await configured_pool(database, monkeypatch)
    actual_migration = db_schema._migration_for_version
    observed = []

    def migration_for_version(version):
        async def migration(connection):
            observed.append(await settings(connection))
            await actual_migration(version)(connection)
        return migration

    monkeypatch.setattr(db_schema, "_migration_for_version", migration_for_version)
    await database.init_database()
    assert len(observed) == 1
    assert observed[0]["statement"] == "2min" and observed[0]["lock"] == "30s"
    async with pool.connection() as connection:
        restored = await settings(connection)
        assert restored["statement"] == "2s" and restored["lock"] == "200ms"
        assert await db_connection._fetchone(
            connection, "SELECT * FROM application_ownership",
        ) is None
        await connection.execute("DROP TABLE application_ownership")
    with pytest.raises(RuntimeError, match="application_ownership"):
        await database.validate_database_schema()


async def test_statement_deadline_rolls_back_and_connection_remains_reusable(database, monkeypatch):
    pool = await configured_pool(database, monkeypatch, statement="1000", lock="100")
    async with pool.connection() as connection:
        started = time.monotonic()
        with pytest.raises(QueryCanceled):
            async with connection.transaction():
                await connection.execute("SELECT pg_sleep(5)")
        assert time.monotonic() - started < 3
        assert await db_connection._fetchone(connection, "SELECT 1 AS usable") == {"usable": 1}


async def test_row_lock_deadline_rolls_back_and_preserves_pool(database, monkeypatch):
    pool = await configured_pool(database, monkeypatch, statement="2000", lock="100")
    await database.init_database()
    async with pool.connection() as blocker:
        await blocker.execute("INSERT INTO application_ownership VALUES (TRUE, gen_random_uuid())")
        async with blocker.transaction():
            await blocker.execute("SELECT * FROM application_ownership FOR UPDATE")
            async with pool.connection() as waiting:
                started = time.monotonic()
                with pytest.raises(LockNotAvailable):
                    async with waiting.transaction():
                        await waiting.execute("SELECT * FROM application_ownership FOR SHARE")
                assert time.monotonic() - started < 1.5
                assert await db_connection._fetchone(waiting, "SELECT 1 AS usable") == {"usable": 1}
    async with pool.connection() as connection:
        assert (await settings(connection))["lock"] == "100ms"


@pytest.mark.parametrize("failure", [QueryCanceled, LockNotAvailable])
async def test_database_timeout_response_is_safe_and_retryable(failure):
    app = FastAPI()
    app.add_exception_handler(failure, main.database_timeout)

    @app.get("/blocked")
    async def blocked():
        raise failure("private database host, statement and credentials")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/blocked")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
