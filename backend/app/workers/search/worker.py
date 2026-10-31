"""Execute durable discovery independently of any client request or polling loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor
from contextvars import copy_context
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.db.search.completion import complete_discovery
from app.db.search.jobs import claim_search, fail_discovery, reserve_external_search
from app.policies.quotas import QuotaExceeded, QuotaUnavailable, classification_admission
from app.workers.contracts import Persistence
from app.workers.jobs import SearchJob
from app.workers.search.discovery import (
    DiscoveryResult,
    lookup_local,
    prepare_repository_candidates,
)
from app.workers.sql_retries import persist_with_retry
from collector.diagnostics import Diagnostic, exception_diagnostics
from collector.observability import emit_event, measure_operation, operation_context
from collector.repository_search import RepositorySearchResponse, search_repository_metadata
from collector.storage.models import CollectedDataset


class SearchWorker:
    """Configure discovery dependencies once; each execution owns its attempt state."""

    name = "search"

    def __init__(
        self,
        *,
        local_lookup: Callable[[str], Awaitable[list[CollectedDataset]]] | None = None,
        provider: Callable[[str], RepositorySearchResponse] | None = None,
        persist: Persistence | None = None,
    ) -> None:
        self._local_lookup = local_lookup if local_lookup is not None else lookup_local
        self._provider = provider if provider is not None else search_repository_metadata
        self._persist: Persistence = persist if persist is not None else persist_with_retry

    async def claim(self, *, claim_token: UUID) -> SearchJob | None:
        """Acquire or recover a search using the same durable claim token."""
        return await claim_search(claim_token=claim_token)

    async def execute(self, job: SearchJob, executor: Executor) -> None:
        """Execute a claimed search locally first, then persist its final outcome."""
        origin = "database"
        saving = False
        with (
            operation_context(search_id=job["id"]),
            measure_operation("search_finished") as measurement,
        ):
            emit_event("search_started", outcome="started")
            try:
                # Catalog hits avoid both the online quota charge and the provider call.
                datasets = await self._local_lookup(job["query"])
                if datasets:
                    result = DiscoveryResult("database", datasets=datasets)
                else:
                    origin = "online"
                    # Reserve once per attempt; False means this claim is no longer current.
                    allowed = await self._persist(lambda: reserve_external_search(job))
                    if not allowed:
                        measurement["outcome"] = "superseded"
                        return
                    # Run blocking provider I/O in a thread with the worker's execution/log context.
                    response = await asyncio.get_running_loop().run_in_executor(
                        executor,
                        copy_context().run,
                        self._provider,
                        job["query"],
                    )
                    result = prepare_repository_candidates(
                        response,
                        job["query"],
                        classification_admission(job["owner_id"], job["client_key"]),
                    )
                # Retain the computed result during SQL retries and distinguish save failures.
                saving = True
                await self._persist(
                    lambda: complete_discovery(job, result),
                    retry_storage_failures=True,
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
                await self._persist(
                    lambda: fail_discovery(
                        job,
                        origin=origin,
                        error=error,
                        diagnostics=[item.to_dict() for item in diagnostics],
                        retry_at=retry_at,
                    ),
                    retry_storage_failures=True,
                    retry_unexpected=True,
                )

    async def recover(self, job: SearchJob) -> object:
        """Record a fenced terminal failure if execution did not finalize the search."""
        return await fail_discovery(
            job,
            origin=job.get("origin", "database"),
            error="Search could not be finalized.",
            diagnostics=[Diagnostic("persistence_failed", "search").to_dict()],
        )
