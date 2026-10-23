"""Accept searches and expose their saved progress to the owning client.

POST /collector/searches calls create_search(), which admits the command and
returns its ID and progress URL. Background workers execute the search.
GET /collector/searches/latest finds the owner's latest search; both this route
and GET /collector/searches/{search_id}/progress use search_progress() to read it.
scripts/api_client.py uses these routes for --query and --latest, then polls
progress while polling_required is true. Reading progress never schedules work.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.auth.security import APIPrincipal, api_auth_mode, quota_http_errors, require_api_principal
from app.db.commands import CommandConflict
from app.db.search_jobs import admit_search
from app.db.search_progress import read_search_progress
from app.db.search_results import latest_search_id
from app.routes.collector_presenters import public_search_progress
from app.routes.collector_schemas import (
    CollectorHTTPError,
    CollectorSearchCommandResponse,
    CollectorSearchCreateRequest,
    CollectorSearchProgressResponse,
)

router = APIRouter(tags=["collector"])

_COMMAND_HEADERS = {
    "Location": {
        "description": "Progress URL path, including the configured ASGI root_path.",
        "schema": {"type": "string"},
    },
    "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
}
# OpenAPI documentation for command responses; handlers set the actual HTTP status.
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
    401: {
        "model": CollectorHTTPError,
        "description": "Missing or invalid visitor session.",
    },
    403: {"model": CollectorHTTPError, "description": "Visitor origin or local access rejected."},
    409: {
        "model": CollectorHTTPError,
        "description": "Command key already used for another operation or payload.",
    },
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

# A required HTTP header used to recognize repeated commands, not an access credential.
CommandKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
]


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
    """Accept a search submitted through POST /collector/searches.

    Save the command for background processing and return its ID and progress URL.
    The search results are retrieved through separate read requests.
    """
    return await _admit_search_command(payload, principal, response, idempotency_key, request)


async def _admit_search_command(payload, principal, response, idempotency_key, request):
    """Validate create_search() input and translate admission failures into HTTP errors.

    admit_search() checks quotas and idempotency in its database transaction.
    row is the saved search; replayed means the command key was already accepted.
    No discovery or model call runs in this HTTP handler.
    """
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


async def _search_command_response(row, replayed, principal, response, request):
    """Build the admission reply from a saved search and its current progress.

    Return 202 for a new command or 200 for a replay, with a Location header and
    progress_url pointing to the read route. This reply contains no dataset list.
    """
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
    """Read the owner's latest search, as requested by the Python client's --latest.

    with_candidates=True selects the latest search with saved candidates instead.
    Reuse search_progress() to return the snapshot; never restart the search.
    """
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
    """Read one owned search and prepare its progress response for the client.

    Called by GET /collector/searches/{search_id}/progress, latest_search(), the
    admission reply and the diagnostic export. The store reads one consistent
    snapshot; public_search_progress() converts it into the response model.
    """
    snapshot = await read_search_progress(search_id, principal.owner_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Search not found")
    response.headers["Cache-Control"] = "no-store"
    return public_search_progress(search_id, snapshot)
