"""Create anonymous cookie sessions for browsers and Python clients in public mode.

Local API access needs no session. In public mode, clients keep the cookie to
access their own searches; browser JavaScript cannot read this HttpOnly cookie.
"""

from fastapi import APIRouter, Request, Response

from app.auth.security import enforce_session_creation_quota, require_public_session_bootstrap
from app.auth.sessions import (
    SESSION_MAX_AGE_SECONDS,
    new_visitor_cookie,
    visitor_owner_id,
)

router = APIRouter(tags=["sessions"])


@router.post("/session", status_code=204)
async def start_visitor_session(request: Request) -> Response:
    """Handle POST /session: keep a valid cookie or set a new anonymous identity.

    require_public_session_bootstrap() checks the public mode and request origin.
    Creating a new identity also checks the session quota. Return HTTP 204 with no
    JSON body.
    """

    settings = require_public_session_bootstrap(request)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    if visitor_owner_id(request.cookies.get(settings.cookie_name), settings) is None:
        await enforce_session_creation_quota(request, settings)
        response.set_cookie(
            settings.cookie_name,
            new_visitor_cookie(settings),
            max_age=SESSION_MAX_AGE_SECONDS,
            path="/",
            secure=settings.secure,
            httponly=True,
            samesite="lax",
        )
    return response
