"""Collector API routes, background orchestration, and response mapping."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Annotated, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response

from app.database import (
    CollectionJobReservation,
    complete_search_session,
    complete_search_session_with_repository_candidates,
    create_search_session,
    enqueue_candidate_classification,
    get_candidate_collection,
    get_collected_datasets,
    get_collection_job_for_owner,
    get_repository_candidate,
    latest_repository_analysis,
    list_collected_datasets,
    search_collected_datasets,
)
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.commands import CommandConflict
from app.db.search_jobs import admit_search
from app.db.search_progress import read_search_progress
from app.db.search_results import latest_search_id
from app.routes.collector_presenters import (
    public_collection_job,
    public_dataset_signals,
    public_repository_classification,
)
from app.routes.collector_schemas import (
    CollectorAutomaticCollection,
    CollectorCollectedDataset,
    CollectorCollectionJobResponse,
    CollectorCollectionResponse,
    CollectorDatabaseDatasetSearchResponse,
    CollectorDistribution,
    CollectorOnlineDatasetSearchResponse,
    CollectorRepositoryCandidateClassificationRequest,
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
    CollectorRepositorySearchWarning,
    CollectorSearchCommandResponse,
    CollectorSearchCreateRequest,
    CollectorSearchProgressResponse,
    CollectorSearchRetryRequest,
    CollectorValidation,
)
from app.search_outcomes import summarize_search
from app.search_service import _bounded_repository_result, lookup_local, prepare_online
from app.security import (
    APIPrincipal,
    api_auth_mode,
    enforce_api_quota,
    enforce_public_online_quota,
    quota_http_errors,
    require_api_principal,
    work_admission,
)
from collector.diagnostics import Diagnostic, exception_diagnostics, public_diagnostics
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

router = APIRouter(prefix="/collector", tags=["collector"])
logger = logging.getLogger(__name__)


@router.get("/collection-jobs/{job_id}")
async def read_collection_job(
    job_id: int,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
) -> CollectorCollectionJobResponse:
    job = await get_collection_job_for_owner(job_id, principal.owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")

    return CollectorCollectionJobResponse(job=public_collection_job(job))


@router.post("/collection-jobs/{job_id}/retry", status_code=202)
async def retry_collection_job(
    job_id: int,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    idempotency_key: Annotated[Optional[str], Header(  # noqa: UP045
        alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$",
    )] = None,
) -> CollectorCollectionJobResponse:
    job = await get_collection_job_for_owner(job_id, principal.owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    try:
        with quota_http_errors():
            job = await retry_collection_job_for_owner(
                job_id, principal.owner_id, admission=work_admission(principal),
                **({"idempotency_key": idempotency_key} if idempotency_key is not None else {}),
            )
    except ValueError as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    return CollectorCollectionJobResponse(job=public_collection_job(job))


@router.get("/collected-datasets")
async def list_collected(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[Optional[int], Query(ge=1, le=2147483647)] = None,  # noqa: UP045
    query: Annotated[str, Query(max_length=300)] = "",
    country: Annotated[str, Query(max_length=200)] = "",
    format: Annotated[str, Query(max_length=100)] = "",
) -> CollectorCollectionResponse:
    datasets = await list_collected_datasets(
        limit=limit + 1, before_id=cursor, query=query, country=country, format=format,
    )
    items = datasets[:limit]
    return CollectorCollectionResponse(
        items=[_collector_collected_dataset(dataset) for dataset in items],
        next_cursor=items[-1].database_id if len(datasets) > limit else None,
    )


@router.get("/collected-datasets/by-id")
async def read_collected_by_id(
    ids: Annotated[list[Annotated[int, Query(ge=1, le=2147483647)]], Query(
        min_length=1, max_length=100,
    )],
) -> CollectorCollectionResponse:
    return CollectorCollectionResponse(
        items=[_collector_collected_dataset(dataset)
               for dataset in await get_collected_datasets(ids)],
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
    try:
        local_datasets = await lookup_local(original_query, lookup=search_collected_datasets)
    except Exception as exception:  # noqa: BLE001 - DB errors must not trigger online calls.
        logger.exception("Collected dataset search failed for query=%r", original_query)
        await _fail_search_session(
            search_id,
            principal.owner_id,
            origin="database",
            error=str(exception),
            errors=[item.to_dict() for item in exception_diagnostics(exception, "search")],
        )
        raise HTTPException(status_code=500, detail="Database search failed.") from exception

    if local_datasets:
        try:
            await complete_search_session(
                search_id,
                principal.owner_id,
                origin="database",
                local_result_count=len(local_datasets),
                local_dataset_ids=[dataset.database_id for dataset in local_datasets],
            )
        except Exception as exception:  # noqa: BLE001 - the search must remain durable.
            logger.exception("Local search completion failed for search_id=%s", search_id)
            await _fail_search_session(
                search_id,
                principal.owner_id,
                origin="database",
                error=str(exception),
                errors=[item.to_dict() for item in exception_diagnostics(exception, "search")],
            )
            raise HTTPException(
                status_code=500,
                detail="Database search failed.",
            ) from exception
        return CollectorDatabaseDatasetSearchResponse(
            search_id=search_id,
            query=original_query,
            items=[_collector_collected_dataset(dataset) for dataset in local_datasets],
        )

    try:
        await enforce_public_online_quota(principal)
        online_response = await _search_online_repositories(original_query)
    except HTTPException as exception:
        await _fail_search_session(
            search_id, principal.owner_id, origin="online", error=str(exception.detail),
            errors=[Diagnostic("api_quota_exceeded" if exception.status_code == 429
                               else "processing_failed", "search").to_dict()],
        )
        raise
    except Exception as exception:  # noqa: BLE001 - provider failures are persisted.
        logger.exception("Repository search failed for search_id=%s", search_id)
        await _fail_search_session(
            search_id,
            principal.owner_id,
            origin="online",
            error=str(exception),
            errors=[item.to_dict() for item in exception_diagnostics(exception, "search")],
        )
        raise HTTPException(status_code=502, detail="Repository search failed.") from exception

    try:
        admission = work_admission(principal)
        prepared = prepare_online(online_response, original_query, admission,
                                  bound=_bounded_repository_result)
        warnings = prepared.warnings
        with quota_http_errors():
            persisted_candidates = await complete_search_session_with_repository_candidates(
                search_id,
                principal.owner_id,
                prepared.candidates,
                status="partial" if warnings else "completed",
                errors=prepared.diagnostics,
                discovery_complete=prepared.complete,
                warnings=prepared.warning_records,
                admission=admission,
            )
    except HTTPException as exception:
        await _fail_search_session(
            search_id, principal.owner_id, origin="online", error=str(exception.detail),
            errors=[Diagnostic("api_quota_exceeded" if exception.status_code == 429
                               else "processing_failed", "search").to_dict()],
        )
        raise
    except Exception as exception:  # noqa: BLE001 - candidates must be durable.
        logger.exception("Online search finalization failed for search_id=%s", search_id)
        await _fail_search_session(
            search_id,
            principal.owner_id,
            origin="online",
            error=str(exception),
            errors=[item.to_dict() for item in exception_diagnostics(exception, "search")],
        )
        raise HTTPException(status_code=500, detail="Database search failed.") from exception

    return CollectorOnlineDatasetSearchResponse(
        search_id=search_id,
        query=original_query,
        items=[_collector_repository_candidate(item) for item in persisted_candidates],
        warnings=[
            _collector_repository_search_warning(warning) for warning in warnings
        ],
    )


async def _search_online_repositories(
    query: str,
) -> RepositorySearchResponse:
    """Run blocking repository providers off the event loop."""

    return await asyncio.to_thread(search_repository_metadata, query)


CommandKey = Annotated[str, Header(
    alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$",
)]


@router.post(
    "/searches", status_code=202,
    responses={200: {"model": CollectorSearchCommandResponse, "description": "Command replay"}},
)
async def create_search(
    payload: CollectorSearchCreateRequest,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    idempotency_key: CommandKey,
) -> CollectorSearchCommandResponse:
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Search query is required")
    try:
        with quota_http_errors():
            row, replayed = await admit_search(
                principal.owner_id, idempotency_key, query=payload.query,
                access_mode=api_auth_mode(), client_key=principal.client_key,
            )
    except CommandConflict as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    return await _search_command_response(row, replayed, principal, response)


@router.post(
    "/searches/{search_id}/retry", status_code=202,
    responses={200: {"model": CollectorSearchCommandResponse, "description": "Command replay"}},
)
async def retry_search(
    search_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    idempotency_key: CommandKey,
    payload: Annotated[Optional[CollectorSearchRetryRequest], Body()] = None,  # noqa: UP045
) -> CollectorSearchCommandResponse:
    del payload
    # Check access before revealing whether a command key or state is eligible.
    if await read_search_progress(search_id, principal.owner_id) is None:
        raise HTTPException(status_code=404, detail="Search not found")
    try:
        with quota_http_errors():
            row, replayed = await admit_search(
                principal.owner_id, idempotency_key, retry_search_id=search_id,
                access_mode=api_auth_mode(), client_key=principal.client_key,
            )
    except CommandConflict as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    return await _search_command_response(row, replayed, principal, response)


async def _search_command_response(row, replayed, principal, response):
    if row is None:
        raise HTTPException(status_code=404, detail="Search not found")
    progress = await search_progress(row["id"], principal, response)
    response.status_code = 200 if replayed else 202
    progress_url = f"/collector/searches/{row['id']}/progress"
    response.headers["Location"] = progress_url
    return CollectorSearchCommandResponse(
        search_id=row["id"], execution_status=progress.execution_status,
        attempt=progress.attempt, progress_url=progress_url,
    )


@router.get("/searches/latest")
async def latest_search(
    principal: Annotated[APIPrincipal, Depends(require_api_principal)], response: Response,
) -> CollectorSearchProgressResponse:
    search_id = await latest_search_id(principal.owner_id)
    if search_id is None:
        raise HTTPException(status_code=404, detail="No previous search")
    return await search_progress(search_id, principal, response)


@router.get("/searches/{search_id}/progress")
async def search_progress(
    search_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
) -> CollectorSearchProgressResponse:
    snapshot = await read_search_progress(search_id, principal.owner_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Search not found")
    search, candidates, collections = snapshot
    items = [
        _collector_repository_candidate(
            candidate,
            automatic_collection=(
                _automatic_collection(collections.get(candidate["id"]))
                if candidate["classification_status"] == "accepted" else None
            ),
        ) for candidate in candidates
    ]
    summary = summarize_search(search, [item.model_dump() for item in items])
    summary["errors"] = public_diagnostics(summary["errors"])
    response.headers["Cache-Control"] = "no-store"
    ids = list(dict.fromkeys([
        *search.get("local_dataset_ids", []),
        *(dataset_id for item in items if item.automatic_collection is not None
          for dataset_id in item.automatic_collection.dataset_ids),
    ]))
    return CollectorSearchProgressResponse(
        search_id=search_id, items=items, query=search.get("query", ""),
        origin=search["origin"] if search["status"] not in {"queued", "running"} else None,
        local_dataset_ids=search.get("local_dataset_ids", []), dataset_ids=ids,
        warnings=search.get("warnings", []), attempt=search.get("attempt_number", 1),
        created_at=str(search.get("created_at", "")), updated_at=str(search.get("updated_at", "")),
        **summary,
    )


@router.get("/repository-analyses/latest")
async def read_latest_repository_analysis(
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
) -> CollectorOnlineDatasetSearchResponse:
    candidates = await latest_repository_analysis(principal.owner_id)
    if not candidates:
        raise HTTPException(status_code=404, detail="No previous repository analysis.")
    return CollectorOnlineDatasetSearchResponse(
        search_id=candidates[0]["search_session_id"],
        query=candidates[0]["search_query"],
        items=[
            await _candidate_with_collection(candidate, principal.owner_id)
            for candidate in candidates
        ],
    )


@router.get("/repository-candidates/{candidate_id}")
async def read_repository_candidate(
    candidate_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
) -> CollectorRepositorySearchItem:
    candidate = await get_repository_candidate(candidate_id, principal.owner_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Repository candidate not found")
    return await _candidate_with_collection(candidate, principal.owner_id)


@router.post(
    "/repository-candidates/{candidate_id}/classify",
    responses={
        202: {
            "model": CollectorRepositorySearchItem,
            "description": "Classification queued or running.",
        }
    },
)
async def classify_repository_result(
    candidate_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    payload: Annotated[
        Optional[CollectorRepositoryCandidateClassificationRequest],  # noqa: UP045
        Body(),
    ] = None,
    retry: bool = False,
    idempotency_key: Annotated[Optional[str], Header(  # noqa: UP045
        alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$",
    )] = None,
) -> CollectorRepositorySearchItem:
    """Persist a request before acknowledging it; never run an LLM in this route."""

    del payload
    candidate = await get_repository_candidate(candidate_id, principal.owner_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Repository candidate not found")
    if idempotency_key is not None:
        try:
            with quota_http_errors():
                candidate = await enqueue_candidate_classification(
                    candidate_id, principal.owner_id, retry=retry,
                    admission=work_admission(principal), idempotency_key=idempotency_key,
                )
        except CommandConflict as exception:
            raise HTTPException(status_code=409, detail=str(exception)) from exception
        if candidate is None:
            raise HTTPException(status_code=404, detail="Repository candidate not found")
        if candidate["classification_status"] in {"queued", "classifying"}:
            response.status_code = 202
        return await _candidate_with_collection(candidate, principal.owner_id)
    status = candidate["classification_status"]
    if status == "error" and not retry:
        raise HTTPException(
            status_code=409, detail="Candidate classification failed; retry explicitly."
        )
    if status == "pending" or (status == "error" and retry):
        with quota_http_errors():
            await enqueue_candidate_classification(
                candidate_id, principal.owner_id, retry=retry, admission=work_admission(principal),
            )
        candidate = await get_repository_candidate(candidate_id, principal.owner_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Repository candidate not found")
    if candidate["classification_status"] in {"queued", "classifying"}:
        response.status_code = 202
    return await _candidate_with_collection(candidate, principal.owner_id)


async def _candidate_with_collection(candidate, owner_id) -> CollectorRepositorySearchItem:
    collection = None
    if candidate["classification_status"] == "accepted":
        collection = _automatic_collection(
            await get_candidate_collection(candidate["id"], owner_id)
        )
    return _collector_repository_candidate(candidate, automatic_collection=collection)


def _automatic_collection(
    collection: CollectionJobReservation | None,
) -> CollectorAutomaticCollection:
    """Present existing follow-up; this function never reserves or schedules work."""

    if collection is not None and collection.already_collected:
        return CollectorAutomaticCollection(
            state="saved", dataset_ids=list(collection.dataset_ids),
            execution_status="finished", outcome="results",
        )
    if collection is None or collection.job is None:
        # Legacy acceptances without follow-up are visible; reading cannot repair
        # them by silently creating new work.
        return CollectorAutomaticCollection(
            state="error", execution_status="failed", outcome="incomplete",
            errors=[Diagnostic("collection_not_scheduled", "collection").to_dict()],
            error="No collection is associated with this candidate.",
            error_code="collection_not_scheduled",
        )
    job = public_collection_job(collection.job)
    state = ("saved" if job.saved_count else "empty") if job.status == "done" else job.status
    return CollectorAutomaticCollection(
        state=state, job=job, dataset_ids=job.dataset_ids,
        execution_status=job.execution_status, outcome=job.outcome, errors=job.errors,
    )


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
        classification_progress=candidate.get("classification_progress", {}),
        classification=public_repository_classification(candidate["classification"]),
        errors=public_diagnostics(candidate.get("errors") or (
            [Diagnostic("legacy_unknown", "classification").to_dict()]
            if candidate["classification_status"] == "error" else []
        )),
        classification_error=(
            "Candidate classification failed."
            if candidate["classification_status"] == "error"
            else ""
        ),
        classification_error_code=(
            "classification_failed" if candidate["classification_status"] == "error" else ""
        ),
        automatic_collection=automatic_collection,
        created_at=candidate["created_at"],
        updated_at=candidate["updated_at"],
    )




async def _fail_search_session(
    search_id: UUID,
    owner_id: str,
    *,
    origin: str,
    error: str,
    errors: list[dict] | None = None,
) -> None:
    """Best-effort terminal update after work outside the search transaction fails."""

    try:
        await complete_search_session(
            search_id,
            owner_id,
            origin=origin,
            status="error",
            error=error or "Search failed.",
            errors=errors,
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
        status=validation.status,
        reason=validation.reason,
        http_status=validation.http_status,
        mime_type=validation.mime_type,
        size_bytes=validation.size_bytes,
        etag=validation.etag,
        last_modified=validation.last_modified,
        content_disposition=validation.content_disposition,
        error="Resource validation failed." if not validation.ok else "",
        error_code="validation_failed" if not validation.ok else "",
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
        date_of_publication=dataset.date_of_publication,
        sharing_license=dataset.sharing_license,
        doi=dataset.doi,
        metadata_provenance=dataset.metadata_provenance,
        discovery_method=dataset.discovery_method,
        dataset_signals=public_dataset_signals(dataset.dataset_signals),
        distributions=[
            _collector_distribution(distribution) for distribution in dataset.distributions
        ],
        validation_results=[
            _collector_validation(validation) for validation in dataset.validation_results
        ],
        first_seen_at=dataset.first_seen_at,
        last_seen_at=dataset.last_seen_at,
        updated_at=dataset.updated_at,
    )
