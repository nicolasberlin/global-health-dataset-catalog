from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.errors import LockNotAvailable, QueryCanceled

from app.auth.security import (
    api_cors_origins,
    configure_access_openapi,
    validate_api_security_configuration,
)
from app.database import (
    close_database_pool,
    init_database,
    mark_interrupted_candidate_classifications_error,
    mark_interrupted_collection_jobs_error,
    mark_interrupted_search_sessions_error,
    open_database_pool,
    validate_database_schema,
)
from app.db.application_lock import application_lock
from app.db.classification_votes import mark_interrupted_votes_error
from app.db.connection import check_database_readiness, configured_database_timeouts
from app.http_limits import (
    RequestBodyLimitMiddleware,
    configured_max_request_body_bytes,
    configured_request_body_timeout_seconds,
)
from app.lifecycle import ApplicationAvailabilityMiddleware, migrate_on_startup
from app.retry_policy import RetryPolicy
from app.routes.collector import router as collector_router
from app.routes.sessions import router as sessions_router
from app.workers.classification import classification_workers
from app.workers.collection import collection_workers
from app.workers.runtime import configured_worker_shutdown_seconds, worker_shutdown_budget
from app.workers.search import search_workers
from app.workers.state import request_worker_stop, workers_ready
from collector.classification.factory import validate_default_classifier_configuration
from collector.config import configured_collection_budget_seconds
from collector.observability import configure_operational_logging


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.ready = False
    application.state.runtime_enforced = True
    application.state.ownership = None
    configure_operational_logging()
    validate_api_security_configuration()
    RetryPolicy.configured()
    configured_collection_budget_seconds()
    configured_max_request_body_bytes()
    configured_request_body_timeout_seconds()
    configured_worker_shutdown_seconds()
    configured_database_timeouts()
    apply_migrations = migrate_on_startup()
    try:
        async with application_lock() as ownership:
            application.state.ownership = ownership
            await open_database_pool()
            try:
                if apply_migrations:
                    await init_database()
                else:
                    await validate_database_schema()
                await ownership.activate()
                await mark_interrupted_search_sessions_error()
                await mark_interrupted_candidate_classifications_error()
                await mark_interrupted_collection_jobs_error()
                await mark_interrupted_votes_error()
                ownership.require_held()
                watcher = asyncio.create_task(_watch_ownership(application, ownership))
                try:
                    async with worker_shutdown_budget(), \
                            collection_workers(), classification_workers(), search_workers():
                        ownership.require_held()
                        application.state.ready = True
                        try:
                            yield
                        finally:
                            application.state.ready = False
                            request_worker_stop()
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
            finally:
                await close_database_pool()
    finally:
        application.state.ready = False
        application.state.ownership = None


async def _watch_ownership(application, ownership) -> None:
    await ownership.lost.wait()
    application.state.ready = False
    request_worker_stop(force=True)


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
