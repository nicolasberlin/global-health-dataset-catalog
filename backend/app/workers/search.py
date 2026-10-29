"""Execute durable discovery independently of any client request or polling loop."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import Executor
from contextvars import copy_context
from datetime import datetime, timedelta, timezone

from app.db.search.jobs import (
    claim_search,
    complete_discovery,
    fail_discovery,
    reserve_external_search,
)
from app.policies.quotas import QuotaExceeded, QuotaUnavailable, classification_admission
from app.search.discovery import DiscoveryResult, lookup_local, prepare_online
from app.workers.jobs import SearchJob
from app.workers.runtime import persisted_workers
from app.workers.sql_retries import persist_with_retry
from collector.diagnostics import Diagnostic, exception_diagnostics
from collector.observability import emit_event, measure_operation, operation_context
from collector.repository_search import search_repository_metadata


async def _run_search(job: SearchJob, executor: Executor) -> None:
    """Execute a claimed search locally first, then persist its final outcome."""
    origin = "database"
    saving = False
    with operation_context(search_id=job["id"]), \
            measure_operation("search_finished") as measurement:
        emit_event("search_started", outcome="started")
        try:
            # Catalog hits avoid both the online quota charge and the provider call.
            datasets = await lookup_local(job["query"])
            if datasets:
                result = DiscoveryResult("database", datasets=datasets)
            else:
                origin = "online"
                # Reserve once per attempt; False means this claim is no longer current.
                allowed = await persist_with_retry(lambda: reserve_external_search(job))
                if not allowed:
                    measurement["outcome"] = "superseded"
                    return
                # Run blocking provider I/O in a thread with the worker's execution/log context.
                response = await asyncio.get_running_loop().run_in_executor(
                    executor,
                    copy_context().run,
                    search_repository_metadata,
                    job["query"],
                )
                result = prepare_online(
                    response,
                    job["query"],
                    classification_admission(job["owner_id"], job["client_key"]),
                )
            # Retain the computed result during SQL retries and distinguish save failures.
            saving = True
            await persist_with_retry(
                lambda: complete_discovery(job, result), retry_storage_failures=True,
            )
        except Exception as exception:  # SQL retries never repeat local/provider discovery.
            measurement["outcome"] = "failed"
            retry_at = None
            if isinstance(exception, QuotaExceeded):
                retry_at = datetime.now(timezone.utc) + timedelta(
                    seconds=exception.retry_after_seconds
                )
                diagnostics = [
                    Diagnostic("api_quota_exceeded", "search", retry_at=retry_at.isoformat())
                ]
            elif isinstance(exception, QuotaUnavailable):
                diagnostics = [Diagnostic("quota_service_unavailable", "search")]
            elif saving:
                diagnostics = [Diagnostic("persistence_failed", "search")]
            else:
                diagnostics = exception_diagnostics(exception, "search")
            error = str(exception) or type(exception).__name__
            await persist_with_retry(
                lambda: fail_discovery(
                    job,
                    origin=origin,
                    error=error,
                    diagnostics=[item.to_dict() for item in diagnostics],
                    retry_at=retry_at,
                ), retry_storage_failures=True, retry_unexpected=True
            )


async def _recover_search(job):
    """Record a terminal failure if execution escaped without finalizing the search."""
    return await fail_discovery(
        job, origin=job.get("origin", "database"), error="Search could not be finalized.",
        diagnostics=[Diagnostic("persistence_failed", "search").to_dict()],
    )


def search_workers(*, concurrency=None, poll_interval=1.0):
    """Manage durable search workers, using SEARCH_MAX_CONCURRENCY by default."""
    return persisted_workers(
        claim=claim_search,
        execute=_run_search,
        recover=_recover_search,
        concurrency=int(os.getenv("SEARCH_MAX_CONCURRENCY", "1"))
        if concurrency is None
        else concurrency,
        name="search",
        poll_interval=poll_interval,
    )
