from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.routes.collector import router as collector_router
from app.security import validate_api_security_configuration


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_api_security_configuration()
    await open_database_pool()
    try:
        await init_database()
        await mark_interrupted_votes_error()
        await mark_interrupted_search_sessions_error()
        await mark_interrupted_candidate_classifications_error()
        await mark_interrupted_collection_jobs_error()
        async with collection_workers(), classification_workers():
            yield
    finally:
        await close_database_pool()


app = FastAPI(title="Global Health API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(collector_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
