"""Owner-scoped diagnostic exports with bounded historical pages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth.security import APIPrincipal, require_api_principal
from app.db.classification_votes import read_candidate_vote_history, read_collection_vote_history
from app.db.collection_traces import read_collection_trace
from app.routes.searches import search_progress

router = APIRouter(tags=["collector"])


@router.get("/repository-candidates/{candidate_id}/classification-history")
async def candidate_classification_history(
    candidate_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
):
    history = await read_candidate_vote_history(
        candidate_id,
        principal.owner_id,
        limit=limit,
        offset=offset,
    )
    if history is None:
        raise HTTPException(status_code=404, detail="Repository candidate not found")
    response.headers["Cache-Control"] = "no-store"
    return history


@router.get("/collection-jobs/{job_id}/classification-history")
async def collection_classification_history(
    job_id: int,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
):
    history = await read_collection_vote_history(
        job_id,
        principal.owner_id,
        limit=limit,
        offset=offset,
    )
    if history is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    response.headers["Cache-Control"] = "no-store"
    return history


@router.get("/collection-jobs/{job_id}/diagnostics")
async def collection_diagnostics(
    job_id: int,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
):
    trace = await read_collection_trace(job_id, principal.owner_id, limit=limit, offset=offset)
    if trace is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    response.headers["Cache-Control"] = "no-store"
    return trace


@router.get("/searches/{search_id}/diagnostics")
async def search_diagnostics(
    search_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
):
    progress = await search_progress(search_id, principal, response)
    job_ids = {
        item.automatic_collection.job.id
        for item in progress.items
        if item.automatic_collection and item.automatic_collection.job
    }
    traces = [await read_collection_trace(job_id, principal.owner_id) for job_id in sorted(job_ids)]
    return {
        "schema_version": "1.0",
        "document_type": "search_diagnostic_trace",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "is_template": False,
        "context": {
            "search_id": str(search_id),
            "query": progress.query,
            "attempt": progress.attempt,
        },
        "summary": progress.model_dump(mode="json"),
        "collections": traces,
        "repository_classifications": [
            {
                "candidate_id": str(item.candidate_id),
                "classification_history": await read_candidate_vote_history(
                    item.candidate_id, principal.owner_id
                ),
            }
            for item in progress.items
        ],
        "export": {
            "method": "persisted_api",
            "coverage": "partial",
            "missing_evidence": [
                "Persisted history can be partial; missing evidence cannot be reconstructed.",
                "Search exports contain bounded history pages; "
                "use the dedicated history endpoints to retrieve older entries when available.",
                "Raw pages, invalid model bodies and cookies are not exported.",
            ],
        },
    }
