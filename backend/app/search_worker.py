"""Execute durable discovery independently of any client request or polling loop."""

from __future__ import annotations

import asyncio
import os
from contextvars import copy_context
from datetime import datetime, timedelta, timezone

from app.db.search_jobs import (
    claim_search,
    complete_discovery,
    fail_discovery,
    reserve_external_search,
)
from app.quota_policy import QuotaExceeded, QuotaUnavailable, classification_admission
from app.search_service import DiscoveryResult, lookup_local, prepare_online
from app.workers import persist_with_retry, persisted_workers
from collector.diagnostics import Diagnostic, exception_diagnostics
from collector.observability import emit_event, measure_operation
from collector.repository_search import search_repository_metadata


async def _run_search(job, executor):
    origin = "database"
    saving = False
    with measure_operation("search_finished") as measurement:
        emit_event("search_started", outcome="started")
        try:
            datasets = await lookup_local(job["query"])
            if datasets:
                result = DiscoveryResult("database", datasets=datasets)
            else:
                origin = "online"
                allowed = await persist_with_retry(lambda: reserve_external_search(job))
                if not allowed:
                    return
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
            saving = True
            await persist_with_retry(lambda: complete_discovery(job, result))
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
                )
            )


def search_workers(*, concurrency=None, poll_interval=1.0):
    return persisted_workers(
        claim=claim_search,
        execute=_run_search,
        concurrency=int(os.getenv("SEARCH_MAX_CONCURRENCY", "1"))
        if concurrency is None
        else concurrency,
        name="search",
        poll_interval=poll_interval,
    )
