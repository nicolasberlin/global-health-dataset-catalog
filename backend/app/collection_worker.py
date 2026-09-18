"""Bounded single-process execution of collection jobs persisted in PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from app.database import (
    claim_pending_collection_job,
    complete_collection_job,
    mark_collection_job_error,
)
from app.workers import persisted_workers
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


def collection_workers(*, concurrency: int | None = None, poll_interval: float = 1.0):
    return persisted_workers(
        claim=claim_pending_collection_job,
        execute=_run_collection_job,
        concurrency=(
            int(os.getenv("COLLECTION_MAX_CONCURRENCY", "2"))
            if concurrency is None
            else concurrency
        ),
        name="collection",
        poll_interval=poll_interval,
    )
