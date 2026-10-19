"""Owner-scoped collection status and retry commands."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.auth.security import APIPrincipal, quota_http_errors, require_api_principal, work_admission
from app.database import get_collection_job_for_owner
from app.db.collection_jobs import retry_collection_job_for_owner
from app.routes.collector_presenters import public_collection_job
from app.routes.collector_schemas import CollectorCollectionJobResponse

router = APIRouter(tags=["collector"])


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
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> CollectorCollectionJobResponse:
    job = await get_collection_job_for_owner(job_id, principal.owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    try:
        with quota_http_errors():
            job = await retry_collection_job_for_owner(
                job_id,
                principal.owner_id,
                admission=work_admission(principal),
                **({"idempotency_key": idempotency_key} if idempotency_key is not None else {}),
            )
    except ValueError as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")
    return CollectorCollectionJobResponse(job=public_collection_job(job))
