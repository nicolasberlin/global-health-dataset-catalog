"""Build the core FastAPI app and expose process health and readiness."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.errors import LockNotAvailable, QueryCanceled

from app.api.middleware import (
    ApplicationAvailabilityMiddleware,
    RequestBodyLimitMiddleware,
    configured_max_request_body_bytes,
    configured_request_body_timeout_seconds,
)
from app.api.router import router as collector_router
from app.api.routes.sessions import router as sessions_router
from app.auth.security import (
    api_cors_origins,
    configure_access_openapi,
)
from app.db.connection import (
    check_database_readiness,
)
from app.lifecycle import lifespan
from app.workers.state import workers_ready
from collector.classification.factory import validate_default_classifier_configuration


async def database_timeout(request, exception) -> JSONResponse:
    return JSONResponse(
        {"detail": "The database is temporarily busy. Please try again later."},
        status_code=503,
        headers={"Retry-After": "5", "Cache-Control": "no-store"},
    )


def health() -> dict[str, str]:
    return {"status": "ok"}


async def ready(request: Request) -> JSONResponse:
    app = request.app
    available = False
    if getattr(app.state, "ready", False) and workers_ready():
        try:
            validate_default_classifier_configuration()
            ownership = getattr(app.state, "ownership", None)
            if getattr(app.state, "runtime_enforced", False):
                if ownership is None or not ownership.healthy:
                    raise RuntimeError("Application ownership is unavailable.")
                ownership.require_held()
            await check_database_readiness()
            available = bool(app.state.ready) and workers_ready()
            if getattr(app.state, "runtime_enforced", False):
                available = (
                    available and ownership is not None
                    and app.state.ownership is ownership and ownership.healthy
                )
        except Exception:
            # Public probes must never expose configuration, connection or error text.
            pass
    return JSONResponse(
        {"status": "ok" if available else "unavailable"},
        status_code=200 if available else 503,
        headers={"Cache-Control": "no-store"},
    )


def create_app() -> FastAPI:
    """Construct an independent core API; optional routes are registered by extensions."""
    application = FastAPI(title="Global Health API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(ApplicationAvailabilityMiddleware)
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=configured_max_request_body_bytes(),
        body_timeout_seconds=configured_request_body_timeout_seconds(),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=api_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After", "Location"],
    )
    application.include_router(collector_router)
    application.include_router(sessions_router)
    application.add_exception_handler(QueryCanceled, database_timeout)
    application.add_exception_handler(LockNotAvailable, database_timeout)
    application.add_api_route("/health", health, methods=["GET"])
    application.add_api_route(
        "/ready", ready, methods=["GET"],
        responses={503: {"description": "Temporarily unavailable"}},
    )
    configure_access_openapi(application)
    return application


app = create_app()
