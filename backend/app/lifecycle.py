"""Own application startup, recovery, background workers and graceful shutdown."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware import (
    configured_max_request_body_bytes,
    configured_request_body_timeout_seconds,
)
from app.auth.security import (
    validate_api_security_configuration,
)
from app.db.classification.candidates import mark_interrupted_candidate_classifications_error
from app.db.classification.votes import mark_interrupted_votes_error
from app.db.collection.jobs import mark_interrupted_collection_jobs_error
from app.db.connection import (
    close_database_pool,
    configured_database_timeouts,
    open_database_pool,
)
from app.db.execution.application_lock import application_lock
from app.db.schema import init_database, validate_database_schema
from app.db.search.sessions import mark_interrupted_search_sessions_error
from app.policies.retries import RetryPolicy
from app.workers.classification.workers import ClassificationWorker
from app.workers.collection.workers import CollectionWorker
from app.workers.runtime import (
    configured_worker_shutdown_seconds,
    persisted_workers,
    worker_shutdown_budget,
)
from app.workers.search.workers import SearchWorker
from app.workers.state import request_worker_stop
from collector.config import configured_collection_budget_seconds
from collector.observability import configure_operational_logging


def migrate_on_startup() -> bool:
    value = os.environ.get("DATABASE_MIGRATE_ON_STARTUP", "true").lower()
    if value not in {"true", "false"}:
        raise ValueError("DATABASE_MIGRATE_ON_STARTUP must be true or false.")
    return value == "true"


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
                    async with (
                        worker_shutdown_budget(),
                        persisted_workers(
                            CollectionWorker(),
                            concurrency=int(os.getenv("COLLECTION_MAX_CONCURRENCY", "2")),
                        ),
                        persisted_workers(
                            ClassificationWorker(),
                            concurrency=int(os.getenv("CLASSIFICATION_MAX_CONCURRENCY", "2")),
                        ),
                        persisted_workers(
                            SearchWorker(),
                            concurrency=int(os.getenv("SEARCH_MAX_CONCURRENCY", "1")),
                        ),
                    ):
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
