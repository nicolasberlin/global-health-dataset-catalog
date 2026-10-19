"""Owner-scoped candidate reads and durable classification commands."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response

from app.auth.security import APIPrincipal, quota_http_errors, require_api_principal, work_admission
from app.database import (
    enqueue_candidate_classification,
    get_candidate_collection,
    get_repository_candidate,
    latest_repository_analysis,
)
from app.db.commands import CommandConflict
from app.routes.collector_presenters import _automatic_collection, _collector_repository_candidate
from app.routes.collector_schemas import (
    CollectorOnlineDatasetSearchResponse,
    CollectorRepositoryCandidateClassificationRequest,
    CollectorRepositorySearchItem,
)

router = APIRouter(tags=["collector"])


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
        CollectorRepositoryCandidateClassificationRequest | None,
        Body(),
    ] = None,
    retry: bool = False,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
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
                    candidate_id,
                    principal.owner_id,
                    retry=retry,
                    admission=work_admission(principal),
                    idempotency_key=idempotency_key,
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
                candidate_id,
                principal.owner_id,
                retry=retry,
                admission=work_admission(principal),
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
