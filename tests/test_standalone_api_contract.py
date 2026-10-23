"""HTTP contracts consumed by an independent client, without a frontend process."""

from __future__ import annotations

from urllib.parse import urljoin
from uuid import UUID

import pytest
from app.db.commands import CommandConflict
from app.quota_policy import QuotaExceeded, QuotaUnavailable
from app.routes import searches
from app.routes.collector import router
from fastapi import FastAPI
from helpers.access import inject_owners
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio
SEARCH_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def contract_api(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    application = FastAPI()
    application.include_router(router)
    return inject_owners(application)


def authorized(key="saved-command-key"):
    return {"X-Test-Owner": "alice", "Idempotency-Key": key}


@pytest.mark.parametrize(
    ("error", "status", "detail", "retry_after"),
    [
        (CommandConflict("Command key already used."), 409, "Command key already used.", None),
        (QuotaExceeded(17, "The search queue is full."), 429, "The search queue is full.", "17"),
        (
            QuotaUnavailable("private database details"), 503,
            "API quota service is unavailable.", None,
        ),
    ],
)
async def test_admission_errors_have_actionable_public_contracts(
    contract_api, monkeypatch, error, status, detail, retry_after
):
    async def reject(*args, **kwargs):
        raise error

    monkeypatch.setattr(searches, "admit_search", reject)
    async with AsyncClient(
        transport=ASGITransport(app=contract_api), base_url="http://test"
    ) as client:
        response = await client.post(
            "/collector/searches", headers=authorized(), json={"query": "mortality"}
        )
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert response.headers.get("retry-after") == retry_after
    assert "location" not in response.headers
    assert "private database" not in response.text




def test_openapi_describes_authentication_commands_and_bounded_result_reads(contract_api):
    schema = contract_api.openapi()
    paths = schema["paths"]
    create = paths["/collector/searches"]["post"]
    assert set(create["responses"]) >= {
        "200",
        "202",
        "400",
        "401",
        "403",
        "409",
        "413",
        "422",
        "429",
        "503",
    }
    for status in ("200", "202"):
        assert "Location" in create["responses"][status]["headers"]
    assert "Retry-After" in create["responses"]["429"]["headers"]
    assert create["responses"]["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CollectorHTTPError"
    }
    key = next(item for item in create["parameters"] if item["name"] == "Idempotency-Key")
    assert key["required"] and key["schema"]["maxLength"] == 128
    assert "HTTPBearer" not in schema["components"]["securitySchemes"]
    assert "security" not in paths["/collector/collected-datasets/by-id"]["get"]
    lookup = paths["/collector/collected-datasets/by-id"]["get"]["parameters"][0]
    assert lookup["schema"]["minItems"] == 1 and lookup["schema"]["maxItems"] == 100
    progress = schema["components"]["schemas"]["CollectorSearchProgressResponse"]
    assert set(progress["properties"]["execution_status"]["enum"]) == {
        "queued",
        "running",
        "waiting_retry",
        "finished",
        "failed",
    }


@pytest.mark.parametrize("prefix", ["", "/gateway/api"])
async def test_location_is_followable_after_creation_and_replay(
    contract_api, monkeypatch, prefix
):
    row = {
        "id": SEARCH_ID,
        "query": "mortality",
        "status": "queued",
        "origin": None,
        "attempt_number": 1,
        "errors": [],
        "warnings": [],
        "local_dataset_ids": [],
    }
    accepted_keys = set()

    async def admit(owner, key, **kwargs):
        assert owner == "alice"
        replayed = key in accepted_keys
        accepted_keys.add(key)
        return row, replayed

    async def progress(search_id, owner):
        return (row, [], {}) if search_id == SEARCH_ID and owner == "alice" else None

    monkeypatch.setattr(searches, "admit_search", admit)
    monkeypatch.setattr(searches, "read_search_progress", progress)
    transport = ASGITransport(app=contract_api, root_path=prefix)
    async with AsyncClient(transport=transport, base_url="https://api.example") as client:
        path = f"{prefix}/collector/searches"
        body = {"query": "mortality"}
        accepted = await client.post(path, headers=authorized(), json=body)
        replay = await client.post(path, headers=authorized(), json=body)
        assert accepted.status_code == 202 and replay.status_code == 200
        assert accepted.json() == replay.json()
        location = accepted.headers["location"]
        assert location == f"{prefix}/collector/searches/{SEARCH_ID}/progress"
        assert accepted.json()["progress_url"] == location
        restored = await client.get(
            urljoin(str(accepted.request.url), location), headers=authorized()
        )
        assert restored.status_code == 200
        assert restored.json()["search_id"] == str(SEARCH_ID)
        assert restored.headers["cache-control"] == "no-store"
        assert accepted.headers["cache-control"] == "no-store"



@pytest.mark.parametrize(
    ("path", "parameters"),
    [
        ("/collector/collected-datasets/by-id", [("ids", index + 1) for index in range(101)]),
        ("/collector/collected-datasets/by-id", {"ids": 0}),
    ],
)
async def test_read_boundaries_reject_unbounded_requests_before_database_access(
    contract_api, path, parameters
):
    async with AsyncClient(
        transport=ASGITransport(app=contract_api), base_url="http://test"
    ) as client:
        response = await client.get(path, params=parameters, headers=authorized())
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
