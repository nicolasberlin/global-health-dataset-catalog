"""Real HTTP frontend and API routes, with isolated persistence fixtures and no workers."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import uvicorn
from app.routes.collector import router as collector_router
from app.routes.sessions import router as sessions_router
from app.security import validate_api_security_configuration
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from collector.storage.models import CollectedDataset

api = FastAPI()
api.include_router(sessions_router)
api.include_router(collector_router)
app = FastAPI()
app.mount("/ai-commons/api", api)
app.mount("/ai-commons", StaticFiles(
    directory=Path(__file__).resolve().parents[2] / "frontend/dist-browser", html=True,
))


@app.get("/", response_class=HTMLResponse)
async def foreign_page():
    return "<!doctype html><title>Foreign origin test</title>"


async def create_search(query, owner_id):
    assert owner_id.startswith("visitor:")
    return {"id": uuid4()}


if __name__ == "__main__":
    os.environ.update(
        API_AUTH_MODE="public",
        API_ALLOW_INSECURE_HTTP_SESSIONS="true",
        API_PUBLIC_ORIGIN="http://localhost:9080",
        API_SESSION_SECRET="browser-test-only-secret-not-for-deployment",
    )
    validate_api_security_configuration()
    dataset = CollectedDataset(
        dataset_url="https://example.org/malaria", title="Malaria browser fixture",
        description="Isolated browser test data", publisher="Test", hosting_platform="Test",
        uploader="Test", dataset_signals={},
    )
    # These replace I/O only: authentication, quotas' HTTP mapping, route validation,
    # response schemas, and the built React application are not mocked.
    with ExitStack() as stack:
        for target, implementation in {
            "app.security.consume_quota_limits": AsyncMock(),
            "app.routes.collector.create_search_session": create_search,
            "app.routes.collector.complete_search_session": AsyncMock(),
            "app.routes.collector.search_collected_datasets": AsyncMock(return_value=[dataset]),
            "app.routes.collector.list_collected_datasets": AsyncMock(return_value=[dataset]),
            "app.routes.collector.latest_repository_analysis": AsyncMock(return_value=[]),
            "app.routes.collector._search_online_repositories": AsyncMock(
                side_effect=AssertionError("Browser tests must not call external providers"),
            ),
        }.items():
            stack.enter_context(patch(target, new=implementation))
        uvicorn.run(app, host="127.0.0.1", port=9080, log_level="warning")
