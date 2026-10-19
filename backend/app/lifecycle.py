"""Admission and startup configuration for the application's owned runtime."""

from __future__ import annotations

import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def migrate_on_startup() -> bool:
    value = os.environ.get("DATABASE_MIGRATE_ON_STARTUP", "true").lower()
    if value not in {"true", "false"}:
        raise ValueError("DATABASE_MIGRATE_ON_STARTUP must be true or false.")
    return value == "true"


class ApplicationAvailabilityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            from app.workers.state import workers_ready

            state = scope["app"].state
            if getattr(state, "runtime_enforced", False):
                ownership = getattr(state, "ownership", None)
                if (
                    not getattr(state, "ready", False)
                    or ownership is None
                    or not ownership.healthy
                    or not workers_ready()
                ):
                    await JSONResponse(
                        {"detail": "Processing is temporarily unavailable."},
                        status_code=503,
                        headers={"Retry-After": "5", "Cache-Control": "no-store"},
                    )(scope, receive, send)
                    return
        await self.app(scope, receive, send)
