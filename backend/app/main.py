from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.classification_worker import classification_workers
from app.collection_worker import collection_workers
from app.database import (
    close_database_pool,
    init_database,
    mark_interrupted_candidate_classifications_error,
    mark_interrupted_collection_jobs_error,
    mark_interrupted_search_sessions_error,
    open_database_pool,
)
from app.db.classification_votes import mark_interrupted_votes_error
from app.db.connection import check_database_readiness
from app.retry_policy import RetryPolicy
from app.routes.collector import router as collector_router
from app.routes.sessions import router as sessions_router
from app.search_worker import search_workers
from app.security import api_cors_origins, validate_api_security_configuration
from collector.classification.factory import validate_default_classifier_configuration
from collector.config import configured_collection_budget_seconds
from collector.observability import configure_operational_logging


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.ready = False
    configure_operational_logging()
    validate_api_security_configuration()
    RetryPolicy.configured()
    configured_collection_budget_seconds()
    await open_database_pool()
    try:
        await init_database()
        await mark_interrupted_votes_error()
        await mark_interrupted_search_sessions_error()
        await mark_interrupted_candidate_classifications_error()
        await mark_interrupted_collection_jobs_error()
        async with collection_workers(), classification_workers(), search_workers():
            application.state.ready = True
            try:
                yield
            finally:
                application.state.ready = False
    finally:
        await close_database_pool()


app = FastAPI(title="Global Health API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=api_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "Location"],
)

app.include_router(collector_router)
app.include_router(sessions_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", responses={503: {"description": "Temporarily unavailable"}})
async def ready() -> JSONResponse:
    available = False
    if getattr(app.state, "ready", False):
        try:
            validate_default_classifier_configuration()
            await check_database_readiness()
            available = bool(app.state.ready)
        except Exception:
            # Public probes must never expose configuration, connection or error text.
            pass
    return JSONResponse(
        {"status": "ok" if available else "unavailable"},
        status_code=200 if available else 503,
        headers={"Cache-Control": "no-store"},
    )
