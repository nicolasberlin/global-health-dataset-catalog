"""Bounded, owned consumers with retained finalization and bounded shutdown."""

from __future__ import annotations

import asyncio
import math
import os
import random as random  # Compatibility export for the shared persistence jitter source.
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from concurrent.futures import Executor
from contextlib import asynccontextmanager
from functools import partial
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from app.db.execution.application_lock import ApplicationLockLost, require_application_ownership
from app.workers.sql_retries import persist_with_retry as _persist_with_retry
from app.workers.state import (
    ShutdownBudget,
    WorkerState,
    current_worker,
    register_worker,
    shutdown_budget,
    unregister_worker,
)
from collector.execution import BoundedThreadExecutor, ExecutionControl, execution_control
from collector.observability import emit_event, operation_context

WorkItem = TypeVar("WorkItem", bound=Mapping[str, object])
ClaimedItem = TypeVar("ClaimedItem", bound=Mapping[str, object], covariant=True)
Execute = Callable[[WorkItem, Executor], Awaitable[None]]
Recover = Callable[[WorkItem], Awaitable[object]]


class Claim(Protocol[ClaimedItem]):
    async def __call__(self, *, claim_token: UUID) -> ClaimedItem | None: ...


async def persist_with_retry(operation, **kwargs):
    """Compatibility export; policy lives independently in app.workers.sql_retries."""
    return await _persist_with_retry(operation, event_sink=emit_event, **kwargs)


def configured_worker_shutdown_seconds() -> float:
    value = float(os.getenv("WORKER_SHUTDOWN_TIMEOUT_SECONDS", "10"))
    if not math.isfinite(value) or not 0 < value <= 300:
        raise ValueError("Worker shutdown timeout must be between zero and 300 seconds.")
    return value


@asynccontextmanager
async def worker_shutdown_budget(*, seconds: float | None = None):
    """Share one drain deadline, activated only when shutdown starts."""
    duration = configured_worker_shutdown_seconds() if seconds is None else seconds
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Worker shutdown timeout must be positive and finite.")
    token = shutdown_budget.set(ShutdownBudget(duration))
    try:
        yield
    finally:
        shutdown_budget.reset(token)


async def _consume(
    stop: asyncio.Event,
    executor: Executor,
    poll_interval: float,
    claim: Claim[WorkItem],
    execute: Execute[WorkItem],
    recover: Recover[WorkItem] | None = None,
) -> None:
    state = current_worker.get()
    while not stop.is_set():
        job = None
        try:
            require_application_ownership()
            # Keep the token until SQL acknowledges acquisition, including a lost commit reply.
            claim_token = uuid4()
            job = await persist_with_retry(
                partial(claim, claim_token=claim_token), log_operation=False, stop=stop,
            )
            if state is not None:
                state.acquisition_failed = False
            if job is not None:
                await execute(job, executor)
                continue
        except ApplicationLockLost:
            raise
        except Exception:
            if job is None and state is not None:
                state.acquisition_failed = True
            identifier = job.get("id") if job is not None else None
            queue = state.queue if state is not None else None
            with operation_context(
                queue=queue, job_id=identifier if queue == "collection" else None,
                candidate_id=identifier if queue == "classification" else None,
                search_id=identifier if queue == "search" else None,
            ):
                emit_event("worker_poll", outcome="failed", error_category="execution")
                if job is not None:
                    if recover is None:
                        if state is not None:
                            state.failed = True
                        raise
                    await persist_with_retry(
                        partial(recover, job), retry_storage_failures=True, retry_unexpected=True,
                    )
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def persisted_workers(
    *, claim: Claim[WorkItem], execute: Execute[WorkItem], concurrency: int, name: str,
    poll_interval: float = 1.0, recover: Recover[WorkItem] | None = None,
    shutdown_timeout: float | None = None,
) -> AsyncIterator[None]:
    """Keep each outcome in its worker slot until acknowledged or shutdown expires.

    Application ownership fences this mono-instance queue. Forced shutdown
    cancels thread bridges and leaves unfinished attempts for startup recovery.
    No in-flight synchronous call can be killed; daemon threads cannot delay exit.
    """
    if concurrency < 1 or poll_interval <= 0:
        raise ValueError("Worker concurrency and polling interval must be positive.")
    duration = (
        configured_worker_shutdown_seconds() if shutdown_timeout is None else shutdown_timeout
    )
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Worker shutdown timeout must be positive and finite.")
    budget = shutdown_budget.get() or ShutdownBudget(duration)
    stop = asyncio.Event()
    executor = BoundedThreadExecutor(max_workers=concurrency, thread_name_prefix=name)
    states = [WorkerState(name, stop, ExecutionControl(), budget) for _ in range(concurrency)]

    async def run(state):
        worker_token = current_worker.set(state)
        execution_token = execution_control.set(state.control)
        try:
            with operation_context(queue=name):
                await _consume(stop, executor, poll_interval, claim, execute, recover)
        except asyncio.CancelledError:
            if not stop.is_set():
                state.failed = True
            raise
        except BaseException:
            state.failed = True
            with operation_context(queue=name):
                emit_event("worker_consumer", outcome="failed", error_category="execution")
        finally:
            execution_control.reset(execution_token)
            current_worker.reset(worker_token)

    for state in states:
        register_worker(state)
        state.task = asyncio.create_task(run(state), name=f"{name}-consumer")
    tasks = [state.task for state in states]
    try:
        yield
    finally:
        budget.start()
        stop.set()
        try:
            remaining = max(0.0, budget.deadline - asyncio.get_running_loop().time())
            _, pending = await asyncio.wait(tasks, timeout=remaining)
            if pending:
                with operation_context(queue=name):
                    emit_event("worker_shutdown", outcome="deadline_exceeded")
        finally:
            for state in states:
                state.control.abort()
                if not state.task.done():
                    state.task.cancel()
            # Database cancellation must not become a second unbounded wait.
            await asyncio.wait(tasks, timeout=0.25)
            for state in states:
                unregister_worker(state)
            executor.shutdown(wait=False, cancel_futures=True)
