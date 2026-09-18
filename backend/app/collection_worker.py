"""Bounded single-process execution of collection jobs persisted in PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from app.database import (
    claim_pending_collection_job,
    complete_collection_job,
    mark_collection_job_error,
)
from collector.main import collect_repository_candidate_with_report, collect_source_with_report

logger = logging.getLogger(__name__)


async def _run_collection_job(job: dict[str, object], executor: ThreadPoolExecutor) -> None:
    """Execute an already claimed job using its authoritative persisted inputs."""

    job_id = int(job["id"])
    try:
        collect = (
            collect_repository_candidate_with_report
            if job["kind"] == "repository_candidate"
            else collect_source_with_report
        )
        result = await asyncio.get_running_loop().run_in_executor(
            executor,
            collect,
            str(job["source_url"]),
        )
        await complete_collection_job(job_id, result)
    except Exception as exception:  # noqa: BLE001 - preserve the job's terminal failure.
        logger.exception("Collection failed for job_id=%s", job_id)
        await mark_collection_job_error(job_id, str(exception) or exception.__class__.__name__)


async def _consume(
    stop: asyncio.Event,
    executor: ThreadPoolExecutor,
    poll_interval: float,
) -> None:
    while not stop.is_set():
        try:
            job = await claim_pending_collection_job()
            if job is not None:
                # One loop owns at most one job until execution AND persistence finish.
                await _run_collection_job(job, executor)
                continue
        except Exception:  # noqa: BLE001 - a temporary DB outage must not kill the consumer.
            logger.exception("Collection worker could not claim or finalize a job")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def collection_workers(
    *,
    concurrency: int | None = None,
    poll_interval: float = 1.0,
) -> AsyncIterator[None]:
    """Drain committed pending jobs without a second in-memory backlog.

    Normal shutdown stops claiming and waits for active jobs to persist their
    outcomes. Forced termination leaves running jobs for startup recovery. Only
    one API process may use this recovery policy; this is not a leased queue.
    """

    if concurrency is None:
        concurrency = int(os.getenv("COLLECTION_MAX_CONCURRENCY", "2"))
    if concurrency < 1 or poll_interval <= 0:
        raise ValueError("Collection concurrency and polling interval must be positive.")
    stop = asyncio.Event()
    executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="collection")
    tasks = [
        asyncio.create_task(_consume(stop, executor, poll_interval)) for _ in range(concurrency)
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
