"""Exclusive application ownership, held outside the query pool before migrations."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from collector.observability import emit_event

from .connection import _database_url_from_env, _fetchone


class ApplicationAlreadyRunning(RuntimeError):
    pass


class ApplicationLockLost(RuntimeError):
    pass


_ownership: ContextVar[ApplicationOwnership | None] = ContextVar(
    "application_ownership", default=None,
)


class ApplicationOwnership:
    def __init__(self, connection, key: int, *, probe_timeout: float = 2.0):
        self.connection, self.key = connection, key
        self.probe_timeout = probe_timeout
        self.lost = asyncio.Event()
        self._mutex = asyncio.Lock()
        self.generation: UUID | None = None

    @property
    def healthy(self) -> bool:
        return not self.lost.is_set() and not self.connection.closed

    def require_held(self) -> None:
        if not self.healthy:
            self._mark_lost()
            raise ApplicationLockLost("Application ownership was lost; restart is required.")

    def _mark_lost(self) -> None:
        if not self.lost.is_set():
            self.lost.set()
            emit_event("application_ownership", outcome="lost")
            from app.workers.state import request_worker_stop
            request_worker_stop(force=True)

    async def check(self) -> None:
        """Check this session's actual lock; never reconnect or silently reacquire it."""
        async with self._mutex:
            await self._check_locked()

    async def activate(self) -> None:
        """Fence previous workers before recovery, using the actual owning session."""
        async with self._mutex:
            await self._check_locked()
            if self.generation is not None:
                return
            generation = uuid4()
            async with self.connection.transaction():
                await self.connection.execute(
                    """INSERT INTO application_ownership (singleton, generation)
                       VALUES (TRUE, %s) ON CONFLICT (singleton)
                       DO UPDATE SET generation = EXCLUDED.generation""",
                    (generation,),
                )
            self.generation = generation

    async def _check_locked(self) -> None:
        self.require_held()
        probe = asyncio.create_task(_fetchone(
            self.connection,
            """SELECT EXISTS(SELECT 1 FROM pg_locks
                   WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                     AND classid = %s::oid AND objid = %s::oid AND objsubid = 1
                     AND granted) AS held""",
            ((self.key >> 32) & 0xFFFFFFFF, self.key & 0xFFFFFFFF),
        ))
        try:
            done, _ = await asyncio.wait({probe}, timeout=self.probe_timeout)
            if not done or probe.result() != {"held": True}:
                raise ApplicationLockLost("Application ownership could not be verified.")
        except asyncio.CancelledError:
            # Monitor cancellation during normal teardown releases ownership cleanly.
            await self.connection.close()
            raise
        except Exception:
            self._mark_lost()
            await self.connection.close()
            raise
        finally:
            if not probe.done():
                # Closing first avoids an unbounded remote query-cancellation roundtrip.
                await self.connection.close()
                probe.cancel()
            await asyncio.gather(probe, return_exceptions=True)


def require_application_ownership() -> None:
    ownership = _ownership.get()
    if ownership is not None:
        ownership.require_held()


async def fence_worker_claim(connection) -> None:
    """Hold the generation row through the claim transaction and receipt replay."""
    ownership = _ownership.get()
    if ownership is None:
        return  # Standalone database operations do not run an application runtime.
    ownership.require_held()
    row = await _fetchone(
        connection, "SELECT generation FROM application_ownership WHERE singleton FOR SHARE",
    )
    if ownership.generation is None or row != {"generation": ownership.generation}:
        ownership._mark_lost()
        raise ApplicationLockLost("Application ownership was replaced; restart is required.")


@asynccontextmanager
async def application_lock(*, probe_interval: float = 1.0, probe_timeout: float = 2.0):
    """Hold one database/schema owner through startup, workers and pool shutdown."""
    if probe_interval <= 0 or probe_timeout <= 0:
        raise ValueError("Ownership probe intervals must be positive.")
    connection = await AsyncConnection.connect(
        _database_url_from_env(), autocommit=True, row_factory=dict_row, connect_timeout=5,
    )
    monitor = None
    token = None
    try:
        await connection.execute("SET statement_timeout = '5s'")
        identity = await _fetchone(connection, """SELECT hashtextextended(
            'global-health-application:' || current_schema(), 0) AS key""")
        key = identity["key"]
        acquired = await _fetchone(
            connection, "SELECT pg_try_advisory_lock(%s) AS acquired", (key,),
        )
        if acquired != {"acquired": True}:
            raise ApplicationAlreadyRunning(
                "Another application already owns this database schema."
            )
        ownership = ApplicationOwnership(connection, key, probe_timeout=probe_timeout)
        token = _ownership.set(ownership)

        async def watch():
            try:
                while True:
                    await asyncio.sleep(probe_interval)
                    await ownership.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                ownership._mark_lost()
                await connection.close()

        monitor = asyncio.create_task(watch(), name="application-ownership")
        yield ownership
    finally:
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if token is not None:
            _ownership.reset(token)
        await connection.close()
