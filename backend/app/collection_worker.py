"""Bounded single-process execution of collection jobs persisted in PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial

from app.database import (
    claim_pending_collection_job,
    complete_collection_job,
    mark_collection_job_error,
)
from app.vote_store import PostgresVoteStore
from app.workers import persist_with_retry, persisted_workers
from collector.classification.factory import build_default_page_classifier
from collector.main import collect_repository_candidate_with_report, collect_source_with_report

logger = logging.getLogger(__name__)


async def _run_collection_job(job: dict[str, object], executor: ThreadPoolExecutor) -> None:
    """Execute an already claimed job using its authoritative persisted inputs."""

    job_id = int(job["id"])
    version = datetime.fromisoformat(str(job["updated_at"]))
    try:
        collect = (
            collect_repository_candidate_with_report
            if job["kind"] == "repository_candidate"
            else collect_source_with_report
        )
        result = await asyncio.get_running_loop().run_in_executor(
            executor,
            partial(collect, classifier=build_default_page_classifier(vote_store=PostgresVoteStore(
                asyncio.get_running_loop(), job_id=job_id,
            ))),
            str(job["source_url"]),
        )
        await persist_with_retry(lambda: complete_collection_job(
            job_id, result, expected_updated_at=version,
        ))
    except Exception as exception:  # noqa: BLE001 - preserve the job's terminal failure.
        logger.exception("Collection failed for job_id=%s", job_id)
        error = str(exception) or exception.__class__.__name__
        await persist_with_retry(lambda: mark_collection_job_error(
            job_id, error, expected_updated_at=version,
        ))


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
