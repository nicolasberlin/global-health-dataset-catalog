"""Collector API routes, background orchestration, and response mapping."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Annotated, Optional, Union
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException

from app.database import (
    complete_candidate_classification,
    complete_collection_job,
    complete_search_session,
    complete_search_session_with_repository_candidates,
    create_search_session,
    fail_candidate_classification,
    get_collection_job,
    get_repository_candidate,
    list_collected_datasets,
    mark_collection_job_error,
    mark_collection_job_running,
    normalize_dataset_search_query,
    reserve_repository_candidate_collection_job,
    search_collected_datasets,
    start_candidate_classification,
)
from app.routes.collector_schemas import (
    CollectorAutomaticCollection,
    CollectorCollectedDataset,
    CollectorCollectionJob,
    CollectorCollectionJobResponse,
    CollectorCollectionResponse,
    CollectorDatabaseDatasetSearchResponse,
    CollectorDistribution,
    CollectorOnlineDatasetSearchResponse,
    CollectorRepositoryCandidateClassificationRequest,
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
    CollectorRepositorySearchWarning,
    CollectorValidation,
)
from app.security import APIPrincipal, enforce_api_quota, require_api_principal
from collector.classification.factory import (
    build_default_repository_result_classifier,
)
from collector.classification.repository import (
    MAX_REPOSITORY_DATE_CHARS,
    MAX_REPOSITORY_DESCRIPTION_CHARS,
    MAX_REPOSITORY_DOI_CHARS,
    MAX_REPOSITORY_KEYWORD_CHARS,
    MAX_REPOSITORY_KEYWORDS,
    MAX_REPOSITORY_METADATA_BYTES,
    MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS,
    MAX_REPOSITORY_METADATA_VALUE_CHARS,
    MAX_REPOSITORY_PUBLISHER_CHARS,
    MAX_REPOSITORY_SEARCH_QUERY_CHARS,
    MAX_REPOSITORY_SOURCE_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
)
from collector.extraction.dataset_metadata import normalize_dataset_metadata
from collector.main import (
    collect_repository_candidate_with_report,
    collect_source_with_report,
)
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.repository_search import (
    classify_repository_result as classify_one_repository_result,
)
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

router = APIRouter(prefix="/collector", tags=["collector"])
logger = logging.getLogger(__name__)

REPOSITORY_CLASSIFICATION_MAX_CONCURRENCY = 2
COLLECTION_MAX_CONCURRENCY = int(os.getenv("COLLECTION_MAX_CONCURRENCY", "2"))
if COLLECTION_MAX_CONCURRENCY < 1:
    raise RuntimeError("COLLECTION_MAX_CONCURRENCY must be greater than zero.")

# A dedicated executor keeps the strict limit until synchronous LLM work really
# finishes, even when the awaiting HTTP request is cancelled.
_repository_classification_executor = ThreadPoolExecutor(
    max_workers=REPOSITORY_CLASSIFICATION_MAX_CONCURRENCY,
    thread_name_prefix="repository-classification",
)
# Collection includes network, page classification, and distribution validation.
# Limiting it server-side protects every client, not only the React application.
_collection_executor = ThreadPoolExecutor(
    max_workers=COLLECTION_MAX_CONCURRENCY,
    thread_name_prefix="collection",
)


@router.get("/collection-jobs/{job_id}")
async def read_collection_job(
    job_id: int,
    _: Annotated[APIPrincipal, Depends(require_api_principal)],
) -> CollectorCollectionJobResponse:
    job = await get_collection_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")

    return CollectorCollectionJobResponse(job=CollectorCollectionJob(**job))


@router.get("/collected-datasets")
async def list_collected() -> CollectorCollectionResponse:
    return CollectorCollectionResponse(
        items=[
            _collector_collected_dataset(dataset)
            for dataset in await list_collected_datasets()
        ],
    )


@router.post("/search-datasets")
async def search_datasets(
    payload: CollectorRepositorySearchRequest,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
) -> Union[  # noqa: UP007 - Python 3.9 cannot parse PEP 604 unions.
    CollectorDatabaseDatasetSearchResponse,
    CollectorOnlineDatasetSearchResponse,
]:
    """Persist one local-first search and its external candidates when needed.

    Database failures are surfaced instead of triggering an external search.
    The original query is stored server-side for providers and later LLM
    classification, so the browser never becomes the authority for that input.
    """

    original_query = payload.query.strip()
    if not original_query:
        raise HTTPException(status_code=400, detail="Search query is required")

    await enforce_api_quota(principal, "repository_search")
    try:
        search_session = await create_search_session(original_query, principal.owner_id)
    except Exception as exception:  # noqa: BLE001 - persistence is required here.
        logger.exception("Search session creation failed for query=%r", original_query)
        raise HTTPException(status_code=500, detail="Database search failed.") from exception

    search_id = search_session["id"]
    if not isinstance(search_id, UUID):
        raise RuntimeError("Search session returned an invalid identifier.")

    # Only PostgreSQL uses the reduced query; the persisted original query is
    # authoritative for providers and downstream LLM classification.
    local_query = normalize_dataset_search_query(original_query)
    try:
        local_datasets = (
            await search_collected_datasets(local_query) if local_query else []
        )
    except Exception as exception:  # noqa: BLE001 - DB errors must not trigger online calls.
        logger.exception("Collected dataset search failed for query=%r", original_query)
        await _fail_search_session(
            search_id,
            principal.owner_id,
            origin="database",
            error=str(exception),
        )
        raise HTTPException(status_code=500, detail="Database search failed.") from exception

    if local_datasets:
        try:
            await complete_search_session(
                search_id,
                principal.owner_id,
                origin="database",
            )
        except Exception as exception:  # noqa: BLE001 - the search must remain durable.
            logger.exception("Local search completion failed for search_id=%s", search_id)
            await _fail_search_session(
                search_id,
                principal.owner_id,
                origin="database",
                error=str(exception),
            )
            raise HTTPException(
                status_code=500,
                detail="Database search failed.",
            ) from exception
        return CollectorDatabaseDatasetSearchResponse(
            search_id=search_id,
            query=original_query,
            items=[
                _collector_collected_dataset(dataset) for dataset in local_datasets
            ],
        )

    try:
        online_response = await _search_online_repositories(original_query)
    except Exception as exception:  # noqa: BLE001 - provider failures are persisted.
        logger.exception("Repository search failed for search_id=%s", search_id)
        await _fail_search_session(
            search_id,
            principal.owner_id,
            origin="online",
            error=str(exception),
        )
        raise HTTPException(status_code=502, detail="Repository search failed.") from exception

    try:
        bounded_results = [
            _bounded_repository_result(item, search_query=original_query)
            for item in online_response.results
        ]
        persisted_candidates = await complete_search_session_with_repository_candidates(
            search_id,
            principal.owner_id,
            bounded_results,
            status="partial" if online_response.warnings else "completed",
        )
    except Exception as exception:  # noqa: BLE001 - candidates must be durable.
        logger.exception("Online search finalization failed for search_id=%s", search_id)
        await _fail_search_session(
            search_id,
            principal.owner_id,
            origin="online",
            error=str(exception),
        )
        raise HTTPException(status_code=500, detail="Database search failed.") from exception

    return CollectorOnlineDatasetSearchResponse(
        search_id=search_id,
        query=original_query,
        items=[_collector_repository_candidate(item) for item in persisted_candidates],
        warnings=[
            _collector_repository_search_warning(warning)
            for warning in online_response.warnings
        ],
    )


async def _search_online_repositories(
    query: str,
) -> RepositorySearchResponse:
    """Run blocking repository providers off the event loop."""

    return await asyncio.to_thread(search_repository_metadata, query)


@router.post("/repository-candidates/{candidate_id}/classify")
async def classify_repository_result(
    candidate_id: UUID,
    background_tasks: BackgroundTasks,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    payload: Annotated[
        Optional[CollectorRepositoryCandidateClassificationRequest],  # noqa: UP045
        Body(),
    ] = None,
    retry: bool = False,
) -> CollectorRepositorySearchItem:
    """Classify the exact candidate metadata previously persisted by the server.

    The empty request contract rejects arbitrary browser metadata. Atomic state
    reservation prevents simultaneous LLM calls, and a failed classification
    can only be retried explicitly with ``retry=true``.
    """

    del payload
    candidate = await get_repository_candidate(candidate_id, principal.owner_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Repository candidate not found")

    if candidate["classification_status"] == "pending" or (
        retry and candidate["classification_status"] == "error"
    ):
        await enforce_api_quota(principal, "repository_classification")

    reserved_candidate = await start_candidate_classification(
        candidate_id,
        principal.owner_id,
        retry=retry,
    )
    if reserved_candidate is None:
        current_candidate = await get_repository_candidate(candidate_id, principal.owner_id)
        if current_candidate is None:
            raise HTTPException(status_code=404, detail="Repository candidate not found")
        status = str(current_candidate["classification_status"])
        if status == "classifying":
            raise HTTPException(status_code=409, detail="Candidate is being classified.")
        if status == "error":
            raise HTTPException(
                status_code=409,
                detail="Candidate classification failed; retry explicitly.",
            )

        automatic_collection = None
        if status == "accepted":
            automatic_collection = await _reserve_automatic_collection(
                candidate_id,
                principal.owner_id,
                background_tasks,
            )
        return _collector_repository_candidate(
            current_candidate,
            automatic_collection=automatic_collection,
        )

    result = _repository_search_result_from_candidate(reserved_candidate)
    try:
        classified_result = await asyncio.get_running_loop().run_in_executor(
            _repository_classification_executor,
            classify_one_repository_result,
            result,
            build_default_repository_result_classifier(),
        )
    except Exception as exception:  # noqa: BLE001 - operational failures are persisted.
        try:
            await fail_candidate_classification(
                candidate_id,
                principal.owner_id,
                str(exception) or exception.__class__.__name__,
            )
        except Exception:  # noqa: BLE001 - preserve the original classifier failure.
            logger.exception(
                "Repository classification failure state could not be saved for "
                "candidate_id=%s",
                candidate_id,
            )
        logger.exception(
            "Repository result classification failed for source=%r url=%s",
            result.source,
            result.url,
        )
        raise HTTPException(status_code=502, detail="Page classification failed.") from exception

    classification = classified_result.classification
    if classification is None:
        await fail_candidate_classification(
            candidate_id,
            principal.owner_id,
            "Repository classifier returned no decision.",
        )
        raise HTTPException(status_code=502, detail="Page classification failed.")

    try:
        completed_candidate = await complete_candidate_classification(
            candidate_id,
            principal.owner_id,
            classification,
        )
    except Exception as exception:  # noqa: BLE001 - DB failures must be visible.
        logger.exception(
            "Repository classification persistence failed for candidate_id=%s",
            candidate_id,
        )
        try:
            await fail_candidate_classification(
                candidate_id,
                principal.owner_id,
                str(exception) or exception.__class__.__name__,
            )
        except Exception:  # noqa: BLE001 - preserve the original persistence failure.
            logger.exception(
                "Repository classification persistence failure state could not be "
                "saved for candidate_id=%s",
                candidate_id,
            )
        raise HTTPException(
            status_code=500,
            detail="Candidate classification could not be saved.",
        ) from exception

    automatic_collection = None
    if classification.accepted:
        automatic_collection = await _reserve_automatic_collection(
            candidate_id,
            principal.owner_id,
            background_tasks,
        )

    return _collector_repository_candidate(
        completed_candidate,
        automatic_collection=automatic_collection,
    )


async def _reserve_automatic_collection(
    candidate_id: UUID,
    owner_id: str,
    background_tasks: BackgroundTasks,
) -> CollectorAutomaticCollection:
    """Reserve one collection job and schedule work only for a new reservation."""

    try:
        reservation = await reserve_repository_candidate_collection_job(
            candidate_id,
            owner_id,
        )
    except Exception:  # noqa: BLE001 - scheduling failures need a stable API error.
        logger.exception(
            "Automatic collection reservation failed for candidate_id=%s",
            candidate_id,
        )
        return CollectorAutomaticCollection(
            state="error",
            error="Automatic collection scheduling failed.",
        )

    if reservation.already_collected:
        return CollectorAutomaticCollection(state="saved")
    if reservation.job is None:
        raise RuntimeError("Automatic collection reservation returned no job.")

    job = CollectorCollectionJob(**reservation.job)
    if reservation.created:
        _schedule_collection_job(background_tasks, job)

    if job.status == "done":
        state = "saved" if job.saved_count else "empty"
    else:
        state = job.status
    return CollectorAutomaticCollection(state=state, job=job)


def _schedule_collection_job(
    background_tasks: BackgroundTasks,
    job: CollectorCollectionJob,
) -> None:
    """Keep in-process scheduling behind one replaceable orchestration point."""

    background_tasks.add_task(
        _run_collection_job,
        job.id,
        job.source_url,
        job.kind == "repository_candidate",
    )


async def _run_collection_job(
    job_id: int,
    source_url: str,
    repository_candidate: bool = False,
) -> None:
    """Collect outside PostgreSQL, then persist datasets and completion atomically.

    Network and LLM work runs in a worker thread before the atomic completion
    transaction begins. Any collection or completion error is recorded in a
    separate transaction by marking the job as failed; if PostgreSQL itself is
    unavailable, that error update can also fail. If the pending-to-running
    transition loses its state race, no collection work is started.
    """

    try:
        running_job = await mark_collection_job_running(job_id)
        if running_job is None:
            return

        collect = (
            collect_repository_candidate_with_report
            if repository_candidate
            else collect_source_with_report
        )
        collection_result = await asyncio.get_running_loop().run_in_executor(
            _collection_executor,
            collect,
            source_url,
        )
        await complete_collection_job(job_id, collection_result)
    except Exception as exception:  # noqa: BLE001 - background jobs must persist failures.
        await mark_collection_job_error(job_id, str(exception))


def _collector_distribution(distribution: DistributionCandidate) -> CollectorDistribution:
    return CollectorDistribution(
        url=distribution.url,
        format=distribution.format,
        probability=distribution.probability,
        anchor=distribution.anchor,
        mime_type=distribution.mime_type,
        first_seen_at=distribution.first_seen_at,
        last_seen_at=distribution.last_seen_at,
        last_checked_at=distribution.last_checked_at,
    )


def _bounded_repository_result(
    item: RepositorySearchResult,
    *,
    search_query: str,
) -> RepositorySearchResult:
    """Apply the API trust-boundary limits before provider metadata is stored."""

    data = asdict(item)
    data["title"] = str(data.get("title", ""))[:MAX_REPOSITORY_TITLE_CHARS]
    data["description"] = str(data.get("description", ""))[
        :MAX_REPOSITORY_DESCRIPTION_CHARS
    ]
    data["source"] = str(data.get("source", ""))[:MAX_REPOSITORY_SOURCE_CHARS]
    data["search_query"] = search_query[:MAX_REPOSITORY_SEARCH_QUERY_CHARS]
    data["publisher"] = str(data.get("publisher", ""))[
        :MAX_REPOSITORY_PUBLISHER_CHARS
    ]
    data["date"] = str(data.get("date", ""))[:MAX_REPOSITORY_DATE_CHARS]
    data["doi"] = str(data.get("doi", ""))[:MAX_REPOSITORY_DOI_CHARS]
    data["keywords"] = [
        str(keyword)[:MAX_REPOSITORY_KEYWORD_CHARS]
        for keyword in data.get("keywords", [])[:MAX_REPOSITORY_KEYWORDS]
    ]
    data["metadata"] = _bounded_repository_metadata(data.get("metadata"))
    data["classification"] = None
    return RepositorySearchResult(**data)


def _collector_repository_candidate(
    candidate: dict[str, object],
    *,
    automatic_collection: CollectorAutomaticCollection | None = None,
) -> CollectorRepositorySearchItem:
    return CollectorRepositorySearchItem(
        candidate_id=candidate["id"],
        search_id=candidate["search_session_id"],
        title=candidate["title"],
        description=candidate["description"],
        url=candidate["url"],
        source=candidate["source"],
        publisher=candidate["publisher"],
        date=candidate["publication_date"],
        doi=candidate["doi"],
        keywords=candidate["keywords"],
        metadata=candidate["metadata"],
        classification_status=candidate["classification_status"],
        classification=candidate["classification"],
        classification_error=candidate["error"],
        automatic_collection=automatic_collection,
        created_at=candidate["created_at"],
        updated_at=candidate["updated_at"],
    )


def _bounded_repository_metadata(value: object) -> dict[str, str]:
    metadata = normalize_dataset_metadata(value if isinstance(value, dict) else {})
    bounded_metadata = {
        key: text[
            :(
                MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS
                if key == "Description of dataset"
                else MAX_REPOSITORY_METADATA_VALUE_CHARS
            )
        ]
        for key, text in metadata.items()
    }

    while _json_size_bytes(bounded_metadata) > MAX_REPOSITORY_METADATA_BYTES:
        largest_key = max(bounded_metadata, key=lambda key: len(bounded_metadata[key]))
        largest_value = bounded_metadata[largest_key]
        if not largest_value:
            break
        bounded_metadata[largest_key] = largest_value[: len(largest_value) // 2]

    return bounded_metadata


def _json_size_bytes(value: dict[str, str]) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
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


async def _fail_search_session(
    search_id: UUID,
    owner_id: str,
    *,
    origin: str,
    error: str,
) -> None:
    """Best-effort terminal update after work outside the search transaction fails."""

    try:
        await complete_search_session(
            search_id,
            owner_id,
            origin=origin,
            status="error",
            error=error or "Search failed.",
        )
    except Exception:  # noqa: BLE001 - preserve the original route failure.
        logger.exception("Search failure state could not be saved for search_id=%s", search_id)


def _collector_repository_search_warning(
    warning: RepositorySearchWarning,
) -> CollectorRepositorySearchWarning:
    return CollectorRepositorySearchWarning(**asdict(warning))


def _collector_validation(validation: ValidationResult) -> CollectorValidation:
    return CollectorValidation(
        url=validation.url,
        final_url=validation.final_url,
        format=validation.format,
        ok=validation.ok,
        http_status=validation.http_status,
        mime_type=validation.mime_type,
        size_bytes=validation.size_bytes,
        etag=validation.etag,
        last_modified=validation.last_modified,
        content_disposition=validation.content_disposition,
        error=validation.error,
    )


def _collector_collected_dataset(dataset: CollectedDataset) -> CollectorCollectedDataset:
    return CollectorCollectedDataset(
        id=dataset.database_id,
        source_url=dataset.source_url,
        dataset_url=dataset.dataset_url,
        title=dataset.title,
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform=dataset.hosting_platform,
        uploader=dataset.uploader,
        geography=list(dataset.geography),
        discovery_method=dataset.discovery_method,
        dataset_signals=dataset.dataset_signals,
        distributions=[
            _collector_distribution(distribution)
            for distribution in dataset.distributions
        ],
        validation_results=[
            _collector_validation(validation)
            for validation in dataset.validation_results
        ],
        first_seen_at=dataset.first_seen_at,
        last_seen_at=dataset.last_seen_at,
        updated_at=dataset.updated_at,
    )
