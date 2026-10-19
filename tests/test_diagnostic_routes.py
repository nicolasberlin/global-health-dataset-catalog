"""Pagination is validated at the diagnostic boundary and keeps owner scope."""

from __future__ import annotations

from uuid import UUID

import pytest
from app.auth.security import APIPrincipal, require_api_principal
from app.routes import diagnostics
from app.routes.collector_presenters import public_collection_job
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio


async def test_collection_diagnostic_page_is_bounded_and_owner_scoped(monkeypatch):
    calls = []

    async def trace(job_id, owner, *, limit, offset):
        calls.append((job_id, owner, limit, offset))
        return {"method_attempts": [], "next_offset": offset + limit}

    app = FastAPI()
    app.include_router(diagnostics.router, prefix="/collector")
    app.dependency_overrides[require_api_principal] = lambda: APIPrincipal("alice")
    monkeypatch.setattr(diagnostics, "read_collection_trace", trace)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for query in ("limit=0", "limit=201", "offset=-1", "offset=10001"):
            rejected = await client.get(f"/collector/collection-jobs/1/diagnostics?{query}")
            assert rejected.status_code == 422
        assert not calls
        response = await client.get("/collector/collection-jobs/1/diagnostics?limit=20&offset=40")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["next_offset"] == 60 and calls == [(1, "alice", 20, 40)]


def test_job_presenter_filters_legacy_observation_and_coverage_fields():
    job = {
        "id": 1,
        "source_url": "https://example.org/data",
        "status": "error",
        "saved_count": 0,
        "method_attempts": [
            {
                "method": "datacite",
                "code": "repository_http_error",
                "body": "private-provider-body",
                "reason": "private-provider-error",
            }
        ],
        "coverage": {"checked": 1, "private": "private-provider-config"},
    }
    result = public_collection_job(job)
    assert result.coverage == {"checked": 1}
    assert "private-provider" not in result.model_dump_json()
    assert result.method_attempts[0]["method"] == "datacite"


@pytest.mark.parametrize(
    ("path", "identifier", "reader"),
    [
        (
            "/repository-candidates/11111111-1111-4111-8111-111111111111/classification-history",
            UUID("11111111-1111-4111-8111-111111111111"),
            "read_candidate_vote_history",
        ),
        ("/collection-jobs/1/classification-history", 1, "read_collection_vote_history"),
    ],
)
async def test_vote_history_pages_validate_bounds_and_keep_owner_access(
    monkeypatch, path, identifier, reader
):
    calls = []

    async def history(identity, owner, *, limit, offset):
        calls.append((identity, owner, limit, offset))
        return {"attempts": [], "next_offset": offset + limit} if offset == 40 else None

    app = FastAPI()
    app.include_router(diagnostics.router, prefix="/collector")
    app.dependency_overrides[require_api_principal] = lambda: APIPrincipal("alice")
    monkeypatch.setattr(diagnostics, reader, history)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rejected = await client.get(f"/collector{path}?limit=201")
        assert rejected.status_code == 422 and not calls
        response = await client.get(f"/collector{path}?limit=20&offset=40")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["next_offset"] == 60
        assert calls == [(identifier, "alice", 20, 40)]
        missing = await client.get(f"/collector{path}")
        assert missing.status_code == 404
