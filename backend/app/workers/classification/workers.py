"""Classify requested candidates independently of HTTP request lifetimes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Executor
from contextvars import copy_context
from datetime import datetime
from uuid import UUID

from app.db.classification.candidates import (
    claim_candidate_classification,
    fail_candidate_classification,
)
from app.db.classification.completion import complete_candidate_classification
from app.db.execution.retries import schedule_llm_retry
from app.workers.contracts import Persistence
from app.workers.failures import FailureHandler
from app.workers.jobs import ClassificationJob
from app.workers.sql_retries import persist_with_retry
from app.workers.stores import PostgresVoteStore

from collector.classification.checkpoints import VoteStore
from collector.classification.factory import build_default_repository_result_classifier
from collector.classification.repository import RepositoryClassification
from collector.diagnostics import Diagnostic
from collector.observability import emit_event, measure_operation, operation_context
from collector.repository_search import RepositorySearchResult
from collector.repository_search import classify_repository_result as classify_one_repository_result


def _classify(
    candidate: ClassificationJob,
    vote_store: VoteStore,
) -> RepositoryClassification | None:
    """Classify persisted metadata with an explicitly scoped vote store."""
    return classify_one_repository_result(
        _repository_search_result_from_candidate(candidate),
        build_default_repository_result_classifier(vote_store=vote_store),
    ).classification


class ClassificationWorker:
    """Execute candidate attempts; shared instances keep no per-attempt state."""

    name = "classification"

    def __init__(
        self,
        *,
        classify: Callable[[ClassificationJob, VoteStore], RepositoryClassification | None]
        | None = None,
        vote_store_factory: Callable[..., VoteStore] | None = None,
        persist: Persistence | None = None,
    ) -> None:
        self._classify = classify if classify is not None else _classify
        self._vote_store_factory = (
            vote_store_factory if vote_store_factory is not None else PostgresVoteStore
        )
        self._persist = persist if persist is not None else persist_with_retry
        self._failures = FailureHandler[ClassificationJob](
            stage="classification",
            retry=self._retry,
            fail=self._fail,
            persist=self._persist,
        )

    async def claim(self, *, claim_token: UUID) -> ClassificationJob | None:
        return await claim_candidate_classification(claim_token=claim_token)

    async def execute(self, candidate: ClassificationJob, executor: Executor) -> None:
        """Retain this attempt's decision until its guarded SQL write succeeds."""
        candidate_id, owner_id = candidate["id"], candidate["owner_id"]
        version = datetime.fromisoformat(str(candidate["updated_at"]))
        with (
            operation_context(candidate_id=candidate_id),
            measure_operation("classification_finished") as measurement,
        ):
            emit_event("classification_started", outcome="started")
            saving = False
            try:
                loop = asyncio.get_running_loop()
                vote_store = self._vote_store_factory(
                    loop,
                    candidate_id=candidate_id,
                    expected_updated_at=version,
                )
                decision = await loop.run_in_executor(
                    executor,
                    copy_context().run,
                    self._classify,
                    candidate,
                    vote_store,
                )
                if decision is None:
                    raise RuntimeError("Repository classifier returned no decision.")
                saving = True
                await self._persist(
                    lambda: complete_candidate_classification(
                        candidate_id,
                        owner_id,
                        decision,
                        expected_updated_at=version,
                    ),
                    retry_storage_failures=True,
                )
            except Exception as exception:
                measurement["outcome"] = "failed"
                await self._failures.handle(candidate, exception, saving=saving)

    async def _retry(
        self,
        candidate: ClassificationJob,
        diagnostics: list[Diagnostic],
    ) -> tuple[bool, list[Diagnostic]]:
        return await schedule_llm_retry(
            candidate["id"],
            datetime.fromisoformat(str(candidate["updated_at"])),
            diagnostics,
            collection=False,
        )

    async def _fail(
        self,
        candidate: ClassificationJob,
        error: str,
        diagnostics: list[Diagnostic],
    ) -> object:
        return await fail_candidate_classification(
            candidate["id"],
            candidate["owner_id"],
            error,
            errors=[item.to_dict() for item in diagnostics],
            expected_updated_at=datetime.fromisoformat(str(candidate["updated_at"])),
        )

    async def recover(self, candidate: ClassificationJob) -> object:
        """Finalize an escaped failure using the original owner and attempt version."""
        return await self._fail(
            candidate,
            "Classification could not be finalized.",
            [Diagnostic("persistence_failed", "classification")],
        )


def _repository_search_result_from_candidate(
    candidate: ClassificationJob,
) -> RepositorySearchResult:
    return RepositorySearchResult(
        title=str(candidate["title"]),
        description=str(candidate["description"]),
        url=str(candidate["url"]),
        source=str(candidate["source"]),
        search_query=str(candidate["search_query"]),
        publisher=str(candidate["publisher"]),
        date=str(candidate["publication_date"]),
        doi=str(candidate["doi"]),
        keywords=list(candidate["keywords"]),
        metadata=dict(candidate["metadata"]),
    )
