"""Bounded consumers for persisted work in a single application process."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

WorkItem = dict[str, object]
Claim = Callable[[], Awaitable[Optional[WorkItem]]]
Execute = Callable[[WorkItem, ThreadPoolExecutor], Awaitable[None]]


async def _consume(
    stop: asyncio.Event,
    executor: ThreadPoolExecutor,
    poll_interval: float,
    claim: Claim,
    execute: Execute,
) -> None:
    while not stop.is_set():
        try:
            job = await claim()
            if job is not None:
                # One loop owns at most one job until execution AND persistence finish.
                await execute(job, executor)
                continue
        except Exception:  # noqa: BLE001 - a temporary DB outage must not kill the consumer.
            logger.exception("Worker could not claim or finalize a task")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def persisted_workers(
    *,
    claim: Claim,
    execute: Execute,
    concurrency: int,
    name: str,
    poll_interval: float = 1.0,
) -> AsyncIterator[None]:
    """Drain committed queued work without a second in-memory backlog.

    Normal shutdown stops claiming and waits for active jobs to persist their
    outcomes. Forced termination leaves running jobs for startup recovery. Only
    one API process may use this recovery policy; this is not a leased queue.
    """

    if concurrency < 1 or poll_interval <= 0:
        raise ValueError("Worker concurrency and polling interval must be positive.")
    stop = asyncio.Event()
    executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=name)
    tasks = [
        asyncio.create_task(_consume(stop, executor, poll_interval, claim, execute))
        for _ in range(concurrency)
    ]
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # No blocking join on the event loop, including during forced cancellation.
            executor.shutdown(wait=False, cancel_futures=True)
