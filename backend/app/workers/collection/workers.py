"""Bounded single-process execution of collection jobs persisted in PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import Executor
from contextvars import copy_context
from dataclasses import replace
from datetime import datetime
from functools import partial
from uuid import UUID

from app.db.collection.completion import complete_collection_job
from app.db.collection.jobs import claim_pending_collection_job, mark_collection_job_error
from app.db.execution.retries import schedule_llm_retry
from app.workers.contracts import Persistence
from app.workers.failures import FailureHandler
from app.workers.jobs import CollectionJob
from app.workers.sql_retries import persist_with_retry
from app.workers.stores import PostgresCollectionTrace, PostgresVoteStore

from collector.budget import collection_budget
from collector.classification.checkpoints import VoteStore
from collector.classification.factory import build_default_page_classifier
from collector.classification.page import PageClassifier
from collector.collection.browser import configured_browser
from collector.config import (
    DEFAULT_CONFIG,
    configured_collection_budget_seconds,
    configured_record_transport,
    configured_repository_connectors,
)
from collector.diagnostics import Diagnostic
from collector.main import collect_repository_candidate_with_report, collect_source_with_report
from collector.observability import emit_event, measure_operation, operation_context
from collector.storage.models import CollectionResult


def _collect_record_job(url, *, classifier, observe):
    hosts = tuple(
        x.strip()
        for x in os.getenv(
            "COLLECTION_DATAVERSE_HOSTS",
            ",".join(DEFAULT_CONFIG.dataverse_hosts),
        ).split(",")
        if x.strip()
    )
    zenodo_hosts = tuple(
        x.strip()
        for x in os.getenv("COLLECTION_ZENODO_HOSTS", "zenodo.org").split(",")
        if x.strip()
    )
    config = replace(
        DEFAULT_CONFIG,
        dataverse_hosts=hosts,
        zenodo_hosts=zenodo_hosts,
        **configured_repository_connectors(),
        **configured_record_transport(),
    )
    with configured_browser(config, source_url=url) as browser:
        return collect_repository_candidate_with_report(
            url, config=config, classifier=classifier, observe=observe, browser=browser
        )


class CollectionWorker:
    """Collect claimed jobs with scoped budgets, votes and optional durable traces."""

    name = "collection"

    def __init__(
        self,
        *,
        classifier_factory: Callable[..., PageClassifier] | None = None,
        vote_store_factory: Callable[..., VoteStore] | None = None,
        trace_factory: Callable[..., PostgresCollectionTrace] | None = None,
        collect_source: Callable[..., CollectionResult] | None = None,
        collect_record: Callable[..., CollectionResult] | None = None,
        persist: Persistence | None = None,
    ) -> None:
        self._classifier_factory = (
            classifier_factory if classifier_factory is not None else build_default_page_classifier
        )
        self._vote_store_factory = (
            vote_store_factory if vote_store_factory is not None else PostgresVoteStore
        )
        self._trace_factory = (
            trace_factory if trace_factory is not None else PostgresCollectionTrace
        )
        self._collect_source = (
            collect_source if collect_source is not None else collect_source_with_report
        )
        self._collect_record = collect_record if collect_record is not None else _collect_record_job
        self._persist = persist if persist is not None else persist_with_retry
        self._failures = FailureHandler[CollectionJob](
            stage="collection",
            retry=self._retry,
            fail=self._fail,
            persist=self._persist,
        )

    async def claim(self, *, claim_token: UUID) -> CollectionJob | None:
        return await claim_pending_collection_job(claim_token=claim_token)

    async def execute(self, job: CollectionJob, executor: Executor) -> None:
        """Compute inside the collection budget; persist outside it without recomputing."""
        job_id = int(job["id"])
        version = datetime.fromisoformat(str(job["updated_at"]))
        with (
            operation_context(job_id=job_id),
            measure_operation("collection_finished") as measurement,
        ):
            emit_event("collection_started", outcome="started")
            saving = False
            try:
                with collection_budget(
                    seconds=configured_collection_budget_seconds(),
                    deadline_at=job.get("collection_deadline_at"),
                ):
                    loop = asyncio.get_running_loop()
                    vote_store = self._vote_store_factory(
                        loop,
                        job_id=job_id,
                        expected_updated_at=version,
                    )
                    classifier = self._classifier_factory(vote_store=vote_store)
                    if job["kind"] == "repository_candidate":
                        observe = self._trace_factory(loop, job_id, version)
                        collect = partial(
                            self._collect_record,
                            classifier=classifier,
                            observe=observe,
                        )
                    else:
                        collect = partial(self._collect_source, classifier=classifier)
                    result = await loop.run_in_executor(
                        executor,
                        copy_context().run,
                        collect,
                        str(job["source_url"]),
                    )
                saving = True
                await self._persist(
                    lambda: complete_collection_job(job_id, result, expected_updated_at=version),
                    retry_storage_failures=True,
                )
            except Exception as exception:
                measurement["outcome"] = "failed"
                await self._failures.handle(job, exception, saving=saving)

    async def _retry(
        self,
        job: CollectionJob,
        diagnostics: list[Diagnostic],
    ) -> tuple[bool, list[Diagnostic]]:
        return await schedule_llm_retry(
            int(job["id"]),
            datetime.fromisoformat(str(job["updated_at"])),
            diagnostics,
            collection=True,
        )

    async def _fail(
        self,
        job: CollectionJob,
        error: str,
        diagnostics: list[Diagnostic],
    ) -> object:
        return await mark_collection_job_error(
            int(job["id"]),
            error,
            errors=[item.to_dict() for item in diagnostics],
            expected_updated_at=datetime.fromisoformat(str(job["updated_at"])),
        )

    async def recover(self, job: CollectionJob) -> object:
        """Finalize an escaped failure without changing this job's fenced version."""
        return await self._fail(
            job,
            "Collection could not be finalized.",
            [Diagnostic("persistence_failed", "collection")],
        )
