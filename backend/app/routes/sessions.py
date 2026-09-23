"""Bootstrap anonymous browser access without returning a credential to JavaScript."""

from fastapi import APIRouter, Request, Response

from app.security import require_public_session_bootstrap
from app.visitor_sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    new_visitor_cookie,
    visitor_owner_id,
)

router = APIRouter(tags=["sessions"])


@router.post("/session", status_code=204)
def start_visitor_session(request: Request) -> Response:
    """Reuse a valid cookie, or create a visitor. Available only in public mode."""

    settings = require_public_session_bootstrap(request)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    if visitor_owner_id(request.cookies.get(SESSION_COOKIE_NAME), settings) is None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            new_visitor_cookie(settings),
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
    return response
