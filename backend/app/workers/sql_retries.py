"""Retry SQL without repeating external work or abandoning its computed outcome."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from typing import TypeVar

from psycopg import InterfaceError, OperationalError
from psycopg.errors import DeadlockDetected, SerializationFailure
from psycopg_pool import PoolTimeout

from app.workers.state import current_worker
from collector.diagnostics import PipelineFailure
from collector.execution import check_execution_active
from collector.observability import emit_event, measure_operation

T = TypeVar("T")
TRANSIENT_SQL_STATES = {"40001", "40P01", "53300", "55P03", "57P01", "57P02", "57P03"}
REPAIRABLE_STORAGE_STATES = {"53100", "53200", "53400", "57014", "58000", "58030"}


def _retryable(exception: Exception, *, retry_storage_failures: bool) -> bool:
    if not isinstance(exception, (OperationalError, InterfaceError, PoolTimeout,
                                  SerializationFailure, DeadlockDetected)):
        return False
    state = exception.sqlstate
    return not state or state.startswith("08") or state in TRANSIENT_SQL_STATES or (
        retry_storage_failures and state in REPAIRABLE_STORAGE_STATES
    )


async def persist_with_retry(
    operation: Callable[[], Awaitable[T]], *, initial_delay: float = 1.0,
    max_delay: float = 30.0, log_operation: bool = True,
    stop: asyncio.Event | None = None, retry_storage_failures: bool = False,
    retry_unexpected: bool = False,
    event_sink=emit_event,
) -> T:
    """Keep the current result until SQL acknowledges its fenced write.

    Normal calls retry only transient SQL failures. Outcome writes also retain
    results during repairable storage failures; terminal failure writes retain
    their slot even for unexpected persistence errors. Acquisition alone may
    interrupt its backoff on graceful stop. Forced cancellation always propagates.
    """
    worker = current_worker.get()
    blocked = False
    with measure_operation("persistence_duration") if log_operation else nullcontext():
        delay, retry_count = initial_delay, 0
        while True:
            check_execution_active()
            # Import lazily: lock bootstrap uses no worker or pool resources.
            from app.db.execution.application_lock import (
                ApplicationLockLost,
                require_application_ownership,
            )
            require_application_ownership()
            if stop is not None and stop.is_set():
                raise asyncio.CancelledError()
            try:
                result = await operation()
                if worker is not None and blocked:
                    worker.blocked_persistence -= 1
                if log_operation:
                    event_sink("persistence_finished", outcome="success", retry_count=retry_count)
                return result
            except Exception as exception:
                if isinstance(exception, (PipelineFailure, ApplicationLockLost)):
                    if worker is not None and blocked:
                        worker.blocked_persistence -= 1
                    raise  # Superseded claims and domain decisions must never loop.
                retryable = _retryable(exception, retry_storage_failures=retry_storage_failures)
                if not retryable and not retry_unexpected:
                    if worker is not None and blocked:
                        worker.blocked_persistence -= 1
                    raise
                degraded = not _retryable(exception, retry_storage_failures=False)
                if worker is not None and degraded and not blocked:
                    worker.blocked_persistence += 1
                    blocked = True
                retry_count += 1
                pause = random.uniform(delay / 2, delay)
                event_sink("persistence_retry", outcome="blocked" if degraded else "retry",
                           retry_count=retry_count, delay_seconds=pause,
                           error_category="storage" if degraded else "database_transient")
                if stop is None:
                    await asyncio.sleep(pause)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=pause)
                    except asyncio.TimeoutError:
                        pass
                delay = min(max_delay, delay * 2)
