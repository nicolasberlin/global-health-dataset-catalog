import json
from uuid import UUID, uuid4

import httpx
import pytest

from search_lab.backend.app import create_app
from search_lab.backend.snapshots import Snapshots

pytestmark = pytest.mark.anyio
SEARCH = UUID("5cf17b2b-88d4-4ef3-8a2f-b000959e776a")


class History:
    async def owns_search(self, owner, search):
        return owner in {"local-user", "alice"} and search == SEARCH

    async def method_claims(self, jobs):
        return {}


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "local")
    app = create_app()
    app.state.history = History()
    app.state.snapshots = Snapshots(tmp_path)
    return app


async def test_capture_only_reads_upstream_and_never_retries(application):
    calls = []

    def upstream(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "context": {"search_id": str(SEARCH), "query": "HIV"},
                "summary": {
                    "items": [
                        {
                            "candidate_id": str(SEARCH),
                            "title": "Survey",
                            "url": "https://example.org/file",
                        }
                    ]
                },
                "collections": [],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="http://main"
    ) as main:
        application.state.client = main
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8003"
        ) as client:
            response = await client.post(
                f"/lab/searches/{SEARCH}/snapshots",
                json={"label": "After", "candidate_id": str(SEARCH)},
                headers={"Origin": "http://127.0.0.1:5174"},
            )
            assert response.status_code == 201
            snapshot = response.json()
            assert snapshot["collector_version"] is None
            assert snapshot["scope"] == "candidate"
            assert snapshot["candidate"]["id"] == str(SEARCH)
            assert len((await client.get("/lab/snapshots")).json()["items"]) == 1
            assert (await client.get("/lab/snapshots/" + snapshot["id"])).status_code == 200
            assert (await client.get("/lab/searches/" + str(uuid4()))).status_code == 404
    assert calls == [("GET", f"/collector/searches/{SEARCH}/diagnostics")]


@pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:5173"])
async def test_lab_refuses_unrelated_browser_origins(application, origin):
    transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8003") as client:
        response = await client.get(f"/lab/searches/{SEARCH}", headers={"Origin": origin})
    assert response.status_code == 403


async def test_token_owner_cannot_read_another_owners_search(application, monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "token")
    token = "bob-test-token-with-at-least-32-characters"
    monkeypatch.setenv("API_ACCESS_TOKENS", json.dumps({"bob": token}))
    transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8003") as client:
        assert (await client.get(f"/lab/searches/{SEARCH}")).status_code == 401
        response = await client.get(
            f"/lab/searches/{SEARCH}", headers={"Authorization": "Bearer " + token}
        )
        assert response.status_code == 404
