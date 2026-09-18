"""Classify requested candidates independently of HTTP request lifetimes."""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from app.database import (
    claim_candidate_classification,
    complete_candidate_classification,
    fail_candidate_classification,
)
from app.workers import persisted_workers
from collector.classification.factory import build_default_repository_result_classifier
from collector.repository_search import RepositorySearchResult
from collector.repository_search import classify_repository_result as classify_one_repository_result

logger = logging.getLogger(__name__)


def _classify(candidate):
    return classify_one_repository_result(
        _repository_search_result_from_candidate(candidate),
        build_default_repository_result_classifier(),
    ).classification


async def _run_classification(candidate: dict[str, object], executor: ThreadPoolExecutor) -> None:
    candidate_id, owner_id = candidate["id"], candidate["owner_id"]
    try:
        decision = await asyncio.get_running_loop().run_in_executor(executor, _classify, candidate)
        if decision is None:
            raise RuntimeError("Repository classifier returned no decision.")
        await complete_candidate_classification(candidate_id, owner_id, decision)
    except Exception as exception:  # noqa: BLE001 - keep internal details and a retryable state.
        logger.exception("Classification failed for candidate_id=%s", candidate_id)
        await fail_candidate_classification(
            candidate_id,
            owner_id,
            str(exception) or exception.__class__.__name__,
        )


def classification_workers(*, concurrency: int | None = None, poll_interval: float = 1.0):
    return persisted_workers(
        claim=claim_candidate_classification,
        execute=_run_classification,
        concurrency=(
            int(os.getenv("CLASSIFICATION_MAX_CONCURRENCY", "2"))
            if concurrency is None
            else concurrency
        ),
        name="classification",
        poll_interval=poll_interval,
    )


def _repository_search_result_from_candidate(
    candidate: dict[str, object],
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
