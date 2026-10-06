from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from typing import Any, Union

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

QueryParameters = Union[Sequence[object], Mapping[str, object], None]
Row = dict[str, Any]

_database_pool: AsyncConnectionPool[DictRow] | None = None
_initialized_pool: AsyncConnectionPool[DictRow] | None = None
READINESS_TIMEOUT_SECONDS = 2.0


async def check_database_readiness() -> None:
    """Probe the initialized pool within one acquisition/query time budget."""
    _require_database_initialized()
    pool = _require_database_pool()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + READINESS_TIMEOUT_SECONDS
    async with pool.connection(timeout=READINESS_TIMEOUT_SECONDS) as connection:
        probe = asyncio.create_task(_fetchone(connection, "SELECT 1 AS ready"))
        try:
            done, _ = await asyncio.wait({probe}, timeout=max(0.0, deadline - loop.time()))
            if not done:
                raise asyncio.TimeoutError("Database readiness timed out.")
            if probe.result() != {"ready": 1}:
                raise RuntimeError("Database readiness probe failed.")
        finally:
            if not probe.done():
                # Close before cancellation: psycopg's normal query cancellation can
                # wait for an unreachable server beyond the readiness time budget.
                await connection.close()
                probe.cancel()
            await asyncio.gather(probe, return_exceptions=True)
    _require_database_initialized()
    if pool is not _require_database_pool():
        raise RuntimeError("Database pool changed during readiness probe.")


def _database_url_from_env() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable must be set to a PostgreSQL "
            "connection URL."
        )
    return database_url


async def open_database_pool() -> None:
    global _database_pool

    if _database_pool is not None:
        return

    pool = AsyncConnectionPool(
        conninfo=_database_url_from_env(),
        min_size=int(os.environ.get("DATABASE_POOL_MIN_SIZE", "1")),
        max_size=int(os.environ.get("DATABASE_POOL_MAX_SIZE", "10")),
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    )
    await pool.open()
    _database_pool = pool
    _set_initialized_pool(None)


async def close_database_pool() -> None:
    global _database_pool

    if _database_pool is None:
        return

    _set_initialized_pool(None)
    await _database_pool.close()
    _database_pool = None


def _set_initialized_pool(pool: AsyncConnectionPool[DictRow] | None) -> None:
    global _initialized_pool
    _initialized_pool = pool


def _require_database_initialized() -> None:
    if _initialized_pool is not _require_database_pool():
        raise RuntimeError("Database schema is not initialized. Run init_database() first.")


def _require_database_pool() -> AsyncConnectionPool[DictRow]:
    if _database_pool is None:
        raise RuntimeError(
            "Database pool is not open. Call open_database_pool() during "
            "application startup before database operations."
        )
    return _database_pool


async def _fetchone(
    connection: AsyncConnection[DictRow],
    sql: str,
    parameters: QueryParameters = None,
) -> Row | None:
    cursor = await connection.execute(sql, parameters)
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def _fetchall(
    connection: AsyncConnection[DictRow],
    sql: str,
    parameters: QueryParameters = None,
) -> list[Row]:
    cursor = await connection.execute(sql, parameters)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
