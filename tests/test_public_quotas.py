"""Public limits must survive cookie resets, concurrent requests and failed transactions."""

from __future__ import annotations

import asyncio

import pytest
from app.db.api_quotas import consume_quota_limits
from app.db.connection import _fetchall, _require_database_pool
from app.quota_policy import QuotaExceeded, classification_admission, public_daily_quota
from app.routes.collector import router as collector_router
from app.routes.sessions import router as sessions_router
from app.security import public_client_key, validate_api_security_configuration
from app.visitor_sessions import VisitorSessionSettings
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from collector.repository_search import RepositorySearchResponse, RepositorySearchResult

pytestmark = pytest.mark.anyio
ORIGIN = "https://health.example"
SECRET = "test-only-public-quota-secret-at-least-32-characters"


@pytest.fixture
async def public_api(database, monkeypatch):
    await database.init_database()
    monkeypatch.setenv("API_AUTH_MODE", "public")
    monkeypatch.setenv("API_SESSION_SECRET", SECRET)
    monkeypatch.setenv("API_PUBLIC_ORIGIN", ORIGIN)
    validate_api_security_configuration()
    app = FastAPI()
    app.include_router(sessions_router)
    app.include_router(collector_router)
    return app


def browser(app, ip="198.51.100.1"):
    return AsyncClient(
        transport=ASGITransport(app=app, client=(ip, 1234)),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    )


async def bootstrap(client):
    response = await client.post("/session")
    assert response.status_code == 204


async def rows(query, parameters=None):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, query, parameters)


def result(index=0):
    return RepositorySearchResult(
        title="Mortality", source="DataCite", url=f"https://example.org/data/{index}"
    )


async def batch(database, owner, *, size=1):
    session = await database.create_search_session("mortality", owner)
    return await database.complete_search_session_with_repository_candidates(
        session["id"],
        owner,
        [result(i) for i in range(size)],
        status="completed",
        admission=classification_admission(owner, f"public:ip:{owner}"),
    )


async def test_session_creation_limit_survives_cookie_reset_and_forwarded_header_spoofing(
    public_api,
    monkeypatch,
):
    monkeypatch.setenv("API_PUBLIC_SESSIONS_PER_IP_PER_MINUTE", "1")
    async with browser(public_api) as alice, browser(public_api) as bob:
        await bootstrap(alice)
        await bootstrap(alice)  # A valid cookie consumes no new issuance quota.
        denied = await bob.post("/session", headers={"X-Forwarded-For": "203.0.113.9"})
        assert denied.status_code == 429
        assert 1 <= int(denied.headers["retry-after"]) <= 60
        assert "set-cookie" not in denied.headers
    async with browser(public_api, "198.51.100.2") as other_ip:
        await bootstrap(other_ip)
    assert len(await rows("SELECT * FROM api_rate_limits")) == 2


async def test_ip_search_quota_cannot_be_reset_by_minting_a_new_cookie(public_api, monkeypatch):
    monkeypatch.setenv("API_PUBLIC_SEARCHES_PER_IP_PER_MINUTE", "1")
    provider_calls = []

    def provider(query):
        provider_calls.append(query)
        return RepositorySearchResponse()

    monkeypatch.setattr("app.routes.collector.search_repository_metadata", provider)
    async with browser(public_api) as alice, browser(public_api) as bob:
        await bootstrap(alice)
        await bootstrap(bob)
        assert (
            await alice.post("/collector/search-datasets", json={"query": "malaria"})
        ).status_code == 200
        denied = await bob.post("/collector/search-datasets", json={"query": "malaria"})
        assert denied.status_code == 429
        assert len(await rows("SELECT * FROM search_sessions")) == 1
        owners = await rows("SELECT * FROM api_rate_limits WHERE owner_id LIKE 'visitor:%'")
        assert len(owners) == 1  # Rejected multi-bucket reservations roll back all their counters.
        before = await rows("SELECT * FROM api_rate_limits ORDER BY owner_id, operation")
        assert (await bob.get("/collector/collected-datasets")).status_code == 200
        assert (await alice.get("/collector/repository-analyses/latest")).status_code == 404
        assert await rows("SELECT * FROM api_rate_limits ORDER BY owner_id, operation") == before
    assert provider_calls == ["malaria"]


async def test_daily_online_budget_blocks_providers_across_visitors_and_ips(
    public_api, monkeypatch
):
    monkeypatch.setenv("API_PUBLIC_ONLINE_SEARCHES_PER_DAY", "1")
    provider_calls = []

    def provider(query):
        provider_calls.append(query)
        return RepositorySearchResponse()

    monkeypatch.setattr("app.routes.collector.search_repository_metadata", provider)
    async with browser(public_api) as alice, browser(public_api, "198.51.100.2") as bob:
        await bootstrap(alice)
        await bootstrap(bob)
        assert (
            await alice.post("/collector/search-datasets", json={"query": "malaria"})
        ).status_code == 200
        denied = await bob.post("/collector/search-datasets", json={"query": "diabetes"})
        assert denied.status_code == 429
        assert 1 <= int(denied.headers["retry-after"]) <= 86400
        assert len(provider_calls) == 1
        failed = await rows("SELECT status FROM search_sessions WHERE query = 'diabetes'")
        assert failed == [{"status": "error"}]


async def test_public_candidate_cap_deduplicates_before_charging(public_api, monkeypatch):
    monkeypatch.setenv("API_PUBLIC_MAX_CANDIDATES_PER_SEARCH", "2")
    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        lambda query: RepositorySearchResponse(
            results=[result(0), result(0), result(1), result(2)]
        ),
    )
    async with browser(public_api) as client:
        await bootstrap(client)
        response = await client.post("/collector/search-datasets", json={"query": "malaria"})
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2
        assert response.json()["warnings"]
        assert await rows("SELECT status FROM search_sessions") == [{"status": "partial"}]
        charged = await rows(
            "SELECT request_count FROM api_rate_limits WHERE operation = 'work_daily'"
        )
        assert charged == [{"request_count": 2}]


async def test_concurrent_batches_cannot_exceed_daily_budget_or_partially_commit(
    database, monkeypatch
):
    await database.init_database()
    monkeypatch.setenv("API_PUBLIC_WORK_ITEMS_PER_DAY", "3")
    outcomes = await asyncio.gather(
        batch(database, "alice", size=2), batch(database, "bob", size=2), return_exceptions=True
    )
    assert sum(isinstance(value, list) for value in outcomes) == 1
    assert sum(isinstance(value, QuotaExceeded) for value in outcomes) == 1
    assert len(await rows("SELECT * FROM repository_candidates")) == 2
    quotas = await rows("SELECT request_count FROM api_rate_limits")
    assert quotas == [{"request_count": 2}] * 3


async def test_batch_larger_than_empty_quota_creates_no_counters_or_candidates(
    database, monkeypatch
):
    await database.init_database()
    monkeypatch.setenv("API_PUBLIC_WORK_ITEMS_PER_DAY", "1")
    with pytest.raises(QuotaExceeded):
        await batch(database, "alice", size=2)
    assert await rows("SELECT * FROM api_rate_limits") == []
    assert await rows("SELECT * FROM repository_candidates") == []


async def test_failure_after_reservation_rolls_back_quota_and_candidates(database):
    await database.init_database()
    session = await database.create_search_session("mortality", "alice")
    await database.complete_search_session(session["id"], "alice", origin="online")
    with pytest.raises(RuntimeError, match="already completed"):
        await database.complete_search_session_with_repository_candidates(
            session["id"],
            "alice",
            [result()],
            status="completed",
            admission=classification_admission("alice", "public:ip:alice"),
        )
    assert await rows("SELECT * FROM api_rate_limits") == []
    assert await rows("SELECT * FROM repository_candidates") == []


async def test_queue_capacity_is_atomic_across_visitors(database, monkeypatch):
    await database.init_database()
    monkeypatch.setenv("API_PUBLIC_MAX_ACTIVE_WORK_ITEMS", "1")
    outcomes = await asyncio.gather(
        batch(database, "alice"), batch(database, "bob"), return_exceptions=True
    )
    assert sum(isinstance(value, list) for value in outcomes) == 1
    assert sum(isinstance(value, QuotaExceeded) for value in outcomes) == 1
    assert len(await rows("SELECT * FROM repository_candidates")) == 1
    assert await rows("SELECT request_count FROM api_rate_limits") == [{"request_count": 1}] * 3


async def test_queue_capacity_includes_collections_and_refusal_charges_nothing(
    database, monkeypatch
):
    await database.init_database()
    monkeypatch.setenv("API_PUBLIC_MAX_ACTIVE_WORK_ITEMS", "1")
    await database.create_collection_job("https://example.org/existing")
    with pytest.raises(QuotaExceeded, match="queue is full"):
        await batch(database, "alice")
    assert await rows("SELECT * FROM api_rate_limits") == []
    assert await rows("SELECT * FROM repository_candidates") == []


async def test_concurrent_classification_retries_consume_one_reservation(database):
    await database.init_database()
    candidates = await batch(database, "alice")
    item = candidates[0]
    await database.claim_candidate_classification()
    await database.fail_candidate_classification(item["id"], "alice", "Provider failed")
    admission = classification_admission("alice", "public:ip:alice")
    outcomes = await asyncio.gather(
        *(
            database.enqueue_candidate_classification(
                item["id"], "alice", retry=True, admission=admission
            )
            for _ in range(6)
        )
    )
    assert sum(value is not None for value in outcomes) == 1
    assert await rows("SELECT request_count FROM api_rate_limits") == [{"request_count": 2}] * 3


async def test_daily_counter_resets_at_the_next_utc_day(database, monkeypatch):
    await database.init_database()
    monkeypatch.setenv("API_PUBLIC_ONLINE_SEARCHES_PER_DAY", "1")
    quotas = (public_daily_quota("online_daily"),)
    await consume_quota_limits(quotas)
    with pytest.raises(QuotaExceeded):
        await consume_quota_limits(quotas)
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE api_rate_limits SET window_started_at = NOW() - INTERVAL '2 days'"
        )
    await consume_quota_limits(quotas)
    assert await rows("SELECT request_count FROM api_rate_limits") == [{"request_count": 1}]


def test_ip_keys_group_ipv6_prefixes_and_do_not_store_raw_addresses():
    settings = VisitorSessionSettings(secret=SECRET, origin=ORIGIN)

    def key(ip):
        request = Request({"type": "http", "client": (ip, 1234), "headers": []})
        return public_client_key(request, settings)

    assert key("2001:db8::1") == key("2001:db8::abcd")
    assert key("2001:db8::1") != key("2001:db8:0:1::1")
    assert key("::ffff:192.0.2.1") == key("192.0.2.1")
    assert "192.0.2.1" not in key("192.0.2.1")


async def test_quota_storage_failure_never_issues_a_session(monkeypatch):
    from app.quota_policy import QuotaUnavailable

    monkeypatch.setenv("API_AUTH_MODE", "public")
    monkeypatch.setenv("API_SESSION_SECRET", SECRET)
    monkeypatch.setenv("API_PUBLIC_ORIGIN", ORIGIN)

    async def unavailable(quotas):
        raise QuotaUnavailable()

    monkeypatch.setattr("app.security.consume_quota_limits", unavailable)
    app = FastAPI()
    app.include_router(sessions_router)
    async with browser(app) as client:
        response = await client.post("/session")
        assert response.status_code == 503
        assert "set-cookie" not in response.headers


async def test_local_results_remain_available_when_external_budget_is_exhausted(
    public_api,
    monkeypatch,
):
    from collector.storage.models import CollectedDataset

    monkeypatch.setenv("API_PUBLIC_ONLINE_SEARCHES_PER_DAY", "1")
    await consume_quota_limits((public_daily_quota("online_daily"),))

    async def local_result(query):
        return [
            CollectedDataset(
                dataset_url="https://example.org/data",
                title="Malaria",
                description="",
                publisher="",
                hosting_platform="",
                uploader="",
                dataset_signals={},
            )
        ]

    def forbidden(query):
        pytest.fail("Local results must not require an external search")

    monkeypatch.setattr("app.routes.collector.search_collected_datasets", local_result)
    monkeypatch.setattr("app.routes.collector.search_repository_metadata", forbidden)
    async with browser(public_api) as client:
        await bootstrap(client)
        response = await client.post("/collector/search-datasets", json={"query": "malaria"})
        assert response.status_code == 200
        assert response.json()["origin"] == "database"
        assert len(response.json()["items"]) == 1


async def test_older_request_timestamp_never_moves_the_quota_window_backward(database):
    await database.init_database()
    await database.consume_api_quota("alice", "repository_search", limit=3)
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE api_rate_limits "
            "SET window_started_at = window_started_at + INTERVAL '1 minute'",
        )
    before = await rows("SELECT window_started_at FROM api_rate_limits")
    assert (await database.consume_api_quota("alice", "repository_search", limit=3)).allowed
    assert await rows("SELECT window_started_at FROM api_rate_limits") == before
    assert await rows("SELECT request_count FROM api_rate_limits") == [{"request_count": 2}]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("API_PUBLIC_WORK_ITEMS_PER_DAY", "0"),
        ("API_PUBLIC_ONLINE_SEARCHES_PER_DAY", "invalid"),
        ("API_PUBLIC_MAX_ACTIVE_WORK_ITEMS", "-1"),
        ("API_PUBLIC_MAX_CANDIDATES_PER_SEARCH", "0"),
    ],
)
def test_public_limits_are_validated_at_startup(monkeypatch, name, value):
    monkeypatch.setenv("API_AUTH_MODE", "public")
    monkeypatch.setenv("API_SESSION_SECRET", SECRET)
    monkeypatch.setenv("API_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=name):
        validate_api_security_configuration()
