"""Durable search commands and owner-scoped progress snapshots."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response

from app.auth.security import APIPrincipal, api_auth_mode, quota_http_errors, require_api_principal
from app.db.commands import CommandConflict
from app.db.search_jobs import admit_search
from app.db.search_progress import read_search_progress
from app.db.search_results import latest_search_id
from app.routes.collector_presenters import public_search_progress
from app.routes.collector_schemas import (
    CollectorHTTPError,
    CollectorRepositorySearchRequest,
    CollectorSearchCommandResponse,
    CollectorSearchCreateRequest,
    CollectorSearchProgressResponse,
    CollectorSearchRetryRequest,
)

router = APIRouter(tags=["collector"])

_COMMAND_HEADERS = {
    "Location": {
        "description": "Progress URL path, including the configured ASGI root_path.",
        "schema": {"type": "string"},
    },
    "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
}
_COMMAND_RESPONSES = {
    200: {
        "model": CollectorSearchCommandResponse,
        "description": "Existing command, with its current state; no duplicate admission.",
        "headers": _COMMAND_HEADERS,
    },
    202: {
        "model": CollectorSearchCommandResponse,
        "description": "Command committed; processing continues without this HTTP client.",
        "headers": _COMMAND_HEADERS,
    },
    400: {"model": CollectorHTTPError, "description": "Search query is blank."},
    401: {"model": CollectorHTTPError, "description": "Missing or invalid deployment credential."},
    403: {"model": CollectorHTTPError, "description": "Visitor origin or local access rejected."},
    409: {"model": CollectorHTTPError, "description": "Command key or retry state conflicts."},
    413: {"model": CollectorHTTPError, "description": "Request body exceeds the configured limit."},
    429: {
        "model": CollectorHTTPError,
        "description": "Quota or queue capacity exceeded; no new command committed.",
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before submitting again.",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
    503: {
        "model": CollectorHTTPError,
        "description": "Authentication, quotas or runtime unavailable.",
    },
}

CommandKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]


@router.post(
    "/search-datasets",
    status_code=202,
    deprecated=True,
    responses=_COMMAND_RESPONSES,
)
async def search_datasets(
    payload: CollectorRepositorySearchRequest,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    request: Request,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
        ),
    ] = None,
) -> CollectorSearchCommandResponse:
    """Deprecated alias of /searches; discovery always runs in the shared worker queue.

    Returns an accepted command and Location, not final dataset results. Legacy
    callers without a command key receive a new server-generated key per POST.
    """

    response.headers["Link"] = f'<{request.url_for("create_search").path}>; rel="successor-version"'
    return await _admit_search_command(
        payload,
        principal,
        response,
        idempotency_key or f"legacy:{uuid4().hex}",
        request,
    )


@router.post(
    "/searches",
    status_code=202,
    responses=_COMMAND_RESPONSES,
)
async def create_search(
    payload: CollectorSearchCreateRequest,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    idempotency_key: CommandKey,
    request: Request,
) -> CollectorSearchCommandResponse:
    return await _admit_search_command(payload, principal, response, idempotency_key, request)


async def _admit_search_command(payload, principal, response, idempotency_key, request):
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Search query is required")
    try:
        with quota_http_errors():
            row, replayed = await admit_search(
                principal.owner_id,
                idempotency_key,
                query=payload.query,
                access_mode=api_auth_mode(),
                client_key=principal.client_key,
            )
    except CommandConflict as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    return await _search_command_response(row, replayed, principal, response, request)


@router.post(
    "/searches/{search_id}/retry",
    status_code=202,
    responses={
        **{status: spec for status, spec in _COMMAND_RESPONSES.items() if status != 400},
        404: {
            "model": CollectorHTTPError,
            "description": "Search absent or owned by another caller.",
        },
    },
)
async def retry_search(
    search_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    idempotency_key: CommandKey,
    request: Request,
    payload: Annotated[CollectorSearchRetryRequest | None, Body()] = None,
) -> CollectorSearchCommandResponse:
    del payload
    # Check access before revealing whether a command key or state is eligible.
    if await read_search_progress(search_id, principal.owner_id) is None:
        raise HTTPException(status_code=404, detail="Search not found")
    try:
        with quota_http_errors():
            row, replayed = await admit_search(
                principal.owner_id,
                idempotency_key,
                retry_search_id=search_id,
                access_mode=api_auth_mode(),
                client_key=principal.client_key,
            )
    except CommandConflict as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    return await _search_command_response(row, replayed, principal, response, request)


async def _search_command_response(row, replayed, principal, response, request):
    if row is None:
        raise HTTPException(status_code=404, detail="Search not found")
    progress = await search_progress(row["id"], principal, response)
    response.status_code = 200 if replayed else 202
    progress_url = request.url_for("search_progress", search_id=str(row["id"])).path
    response.headers["Location"] = progress_url
    return CollectorSearchCommandResponse(
        search_id=row["id"],
        execution_status=progress.execution_status,
        attempt=progress.attempt,
        progress_url=progress_url,
    )


@router.get("/searches/latest")
async def latest_search(
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
    with_candidates: bool = False,
) -> CollectorSearchProgressResponse:
    search_id = await latest_search_id(
        principal.owner_id,
        **({"with_candidates": True} if with_candidates else {}),
    )
    if search_id is None:
        raise HTTPException(
            status_code=404,
            detail="No previous external analysis" if with_candidates else "No previous search",
        )
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
    response.headers["Cache-Control"] = "no-store"
    return public_search_progress(search_id, snapshot)
