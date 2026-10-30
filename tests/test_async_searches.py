"""Durable API commands: no browser orchestrator, including retries and reconnects."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from types import SimpleNamespace

import psycopg
import pytest
from app.db.connection import _require_database_pool
from app.db.execution.commands import CommandConflict
from app.db.search import jobs as search_jobs
from app.policies.quotas import QuotaExceeded
from app.workers.classification import workers as classification_worker
from app.workers.collection import workers as collection_worker
from app.workers.runtime import persisted_workers
from app.workers.search import workers as search_worker
from app.workers.search.discovery import DiscoveryResult
from app.workers.sql_retries import persist_with_retry
from helpers.inspection import stored_candidate
from helpers.workflows import candidate, headers, read, rows, wait_until
from helpers.workflows import classification_decision as decision
from httpx import ASGITransport, AsyncClient

from collector.repository_search import (
    DataCiteRepositorySearchProvider,
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.storage.models import CollectedDataset, CollectionReport, CollectionResult

pytestmark = pytest.mark.anyio


def browser(application):
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


async def admit(key="first", **kwargs):
    return await search_jobs.admit_search(
        "alice",
        key,
        access_mode="local",
        client_key=None,
        **kwargs,
    )


def provider_result():
    return RepositorySearchResult(title="Mortality", url="https://example.org/data", source="test")


async def run(job):
    with ThreadPoolExecutor(max_workers=1) as executor:
        await search_worker.SearchWorker().execute(job, executor)


async def test_removed_repository_analysis_route_is_absent(api):
    path = "/collector/repository-analyses/latest"
    schema = api.openapi()
    assert path not in schema["paths"]
    assert "CollectorOnlineDatasetSearchResponse" not in schema["components"]["schemas"]
    async with browser(api) as client:
        for request_headers in ({}, headers()):
            response = await client.get(path, headers=request_headers)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not Found"}


async def test_restore_external_analysis_skips_newer_local_search_and_preserves_owner(
    database, api,
):
    await database.init_database()
    external = await candidate(database, query="tuberculosis")
    await database.complete_search_session(
        external["search_session_id"], "alice", origin="online",
    )
    local = await database.create_search_session("tuberculosis", "alice")
    await database.complete_search_session(local["id"], "alice", origin="database")
    bob = await database.create_search_session("tuberculosis", "bob")
    await database.complete_search_session(bob["id"], "bob", origin="database")
    async with browser(api) as client:
        latest = await client.get("/collector/searches/latest", headers=headers())
        assert latest.status_code == 200
        assert latest.json()["search_id"] == str(local["id"])
        restored = await client.get(
            "/collector/searches/latest?with_candidates=true", headers=headers(),
        )
        assert restored.status_code == 200
        assert restored.json()["search_id"] == str(external["search_session_id"])
        assert restored.json()["origin"] == "online"
        assert "execution_status" in restored.json()
        assert "polling_required" in restored.json()
        assert [item["candidate_id"] for item in restored.json()["items"]] == [str(external["id"])]
        assert (await client.get(
            "/collector/searches/latest?with_candidates=true", headers=headers("bob"),
        )).status_code == 404
    assert len(await rows("SELECT * FROM search_sessions")) == 3
    assert not await rows("SELECT * FROM collection_jobs")


async def test_single_post_then_disconnected_client_completes_all_stages(
    database,
    api,
    monkeypatch,
):
    await database.init_database()
    calls = []

    def discover(query):
        calls.append("discovery")
        return RepositorySearchResponse(results=[provider_result()])

    def classify(item, vote_store):
        calls.append("classification")
        assert item["search_query"] == "mortality"
        return decision()

    def collect(url, **kwargs):
        calls.append("collection")
        return CollectionResult(
            report=CollectionReport(verification_complete=True),
            datasets=[
                CollectedDataset(
                    dataset_url=url,
                    title="Mortality",
                    description="",
                    publisher="",
                    hosting_platform="",
                    uploader="",
                    dataset_signals={},
                )
            ],
        )

    monkeypatch.setattr(search_worker, "search_repository_metadata", discover)
    monkeypatch.setattr(classification_worker, "_classify", classify)
    monkeypatch.setattr(collection_worker, "build_default_page_classifier", lambda **_: object())
    monkeypatch.setattr(collection_worker, "collect_repository_candidate_with_report", collect)
    async with browser(api) as client:
        created = await client.post(
            "/collector/searches",
            json={"query": "mortality"},
            headers={**headers(), "Idempotency-Key": "pipeline"},
        )
        assert created.status_code == 202
    # The HTTP client is closed. Workers use only persisted state; no progress/classify calls.
    async with (
        persisted_workers(search_worker.SearchWorker(), poll_interval=0.01, concurrency=1),
        persisted_workers(
            classification_worker.ClassificationWorker(), poll_interval=0.01, concurrency=2
        ),
        persisted_workers(collection_worker.CollectionWorker(), poll_interval=0.01, concurrency=2),
    ):

        async def finished():
            jobs = await rows("SELECT status FROM collection_jobs")
            return bool(jobs) and jobs[0]["status"] == "done"

        await wait_until(finished)
    assert calls == ["discovery", "classification", "collection"]
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    async with browser(api) as client:
        progress = (await client.get(created.json()["progress_url"], headers=headers())).json()
        assert progress["execution_status"] == "finished" and not progress["polling_required"]
        assert progress["outcome"] == "results" and len(progress["dataset_ids"]) == 1
        assert (
            await client.get("/collector/searches/latest", headers=headers())
        ).json() == progress
        datasets = await client.get(
            "/collector/collected-datasets/by-id", params={"ids": progress["dataset_ids"]}
        )
        assert datasets.json()["items"][0]["title"] == "Mortality"


async def test_local_ranked_results_and_legacy_completion_are_atomic(database, monkeypatch):
    await database.init_database()
    async with _require_database_pool().connection() as connection:
        cursor = await connection.execute(
            "INSERT INTO collected_datasets (dataset_url, title) VALUES "
            "('https://example.org/1', 'Health'), ('https://example.org/2', 'Health') RETURNING id"
        )
        ids = [row["id"] for row in await cursor.fetchall()][::-1]

    async def local(query):
        return [SimpleNamespace(database_id=id) for id in ids]

    monkeypatch.setattr(search_worker, "lookup_local", local)
    monkeypatch.setattr(
        search_worker, "search_repository_metadata", lambda _: pytest.fail("provider")
    )
    session, _ = await admit(query="health")
    await run(await search_jobs.claim_search())
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    result = await read(session["id"])
    assert result.local_dataset_ids == result.dataset_ids == ids
    assert result.outcome == "results" and result.origin == "database"
    assert not await rows("SELECT * FROM repository_candidates")
    legacy = await database.create_search_session("legacy", "alice")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await database.complete_search_session(
            legacy["id"], "alice", origin="database", local_dataset_ids=[2147483647]
        )
    assert (await read(legacy["id"])).execution_status == "running"


@pytest.mark.parametrize("warning", [False, True])
async def test_empty_vs_unavailable_discovery_and_durable_warning(database, monkeypatch, warning):
    await database.init_database()
    monkeypatch.setattr(
        search_worker,
        "search_repository_metadata",
        lambda _: RepositorySearchResponse(
            results=[],
            warnings=[RepositorySearchWarning(provider="DataCite", message="private secret")]
            if warning
            else [],
        ),
    )
    session, _ = await admit(query="health")
    await run(await search_jobs.claim_search())
    result = await read(session["id"])
    assert result.outcome == ("incomplete" if warning else "empty")
    assert not result.polling_required
    assert "private secret" not in result.model_dump_json()
    if warning:
        assert result.warnings[0].provider == "DataCite"
        assert result.warnings[0].incomplete
        retried, _ = await admit("retry", retry_search_id=session["id"])
        assert retried["status"] == "queued" and retried["attempt_number"] == 2
    else:
        with pytest.raises(CommandConflict):
            await admit("retry", retry_search_id=session["id"])


async def test_partial_datacite_warning_and_usable_candidates_survive_restart(
    database, monkeypatch,
):
    await database.init_database()
    unsafe_html = "<div>" * 129 + "unsafe" + "</div>" * 129
    provider = DataCiteRepositorySearchProvider(
        fetch_json=lambda _: {
            "data": [
                {"id": "10.1234/unsafe", "attributes": {"titles": [{"title": unsafe_html}]}},
                {"id": "10.1234/valid", "attributes": {"titles": [{"title": "Valid dataset"}]}},
            ],
        },
    )
    monkeypatch.setattr(
        search_worker,
        "search_repository_metadata",
        lambda query: search_repository_metadata(query, providers=[provider]),
    )
    session, _ = await admit(query="health")
    await run(await search_jobs.claim_search())
    valid = await database.claim_candidate_classification()
    await database.complete_candidate_classification(valid["id"], "alice", decision(False))
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()

    result = await read(session["id"])
    assert result.outcome == "incomplete"
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "invalid_repository_metadata"
    assert result.warnings[0].provider == "DataCite"
    assert result.warnings[0].incomplete
    candidates = await rows(
        "SELECT candidate.title, session.query AS search_query "
        "FROM repository_candidates AS candidate "
        "JOIN search_sessions AS session ON session.id = candidate.search_session_id"
    )
    assert candidates == [{"title": "Valid dataset", "search_query": "health"}]


async def test_restart_preserves_queue_fences_old_attempt_and_late_command_replay(database):
    await database.init_database()
    first, _ = await admit(query="first")
    old = await search_jobs.claim_search()
    second, _ = await admit("second", query="second")
    await database.mark_interrupted_search_sessions_error()
    assert (await read(first["id"])).execution_status == "failed"
    assert (await read(second["id"])).execution_status == "queued"
    retried, replay = await admit("retry", retry_search_id=first["id"])
    assert retried["attempt_number"] == 2 and not replay
    new = await search_jobs.claim_search()
    assert new["id"] == first["id"]
    assert not await search_jobs.complete_discovery(old, DiscoveryResult("online"))
    assert not await search_jobs.fail_discovery(old, origin="online", error="old", diagnostics=[])
    await search_jobs.complete_discovery(new, DiscoveryResult("online"))
    late, replay = await admit("retry", retry_search_id=first["id"])
    assert replay and late["status"] == "completed" and late["attempt_number"] == 2
    original, replay = await admit(query="first")
    assert replay and original["status"] == "completed"
    assert (await read(first["id"])).outcome == "empty"


async def test_full_queue_rolls_back_receipts_and_quota(database, monkeypatch):
    await database.init_database()
    monkeypatch.setenv("SEARCH_MAX_ACTIVE", "1")
    results = await asyncio.gather(
        admit("a", query="a"), admit("b", query="b"), return_exceptions=True
    )
    assert sum(isinstance(item, QuotaExceeded) for item in results) == 1
    assert len(await rows("SELECT * FROM search_sessions")) == 1
    assert len(await rows("SELECT * FROM api_commands")) == 1
    assert (await rows("SELECT * FROM api_rate_limits"))[0]["request_count"] == 1


async def test_public_quota_is_once_per_attempt_and_retry_after_is_enforced(database, monkeypatch):
    await database.init_database()
    monkeypatch.setenv("API_PUBLIC_ONLINE_SEARCHES_PER_DAY", "1")
    create = partial(search_jobs.admit_search, "alice", access_mode="public", client_key="ip-hash")
    session, _ = await create("first", query="health")
    job = await search_jobs.claim_search()
    assert job["client_key"] == "ip-hash" and job["access_mode"] == "public"
    assert await search_jobs.reserve_external_search(job)
    assert await search_jobs.reserve_external_search(job)  # Lost acknowledgement replay.
    await search_jobs.complete_discovery(job, DiscoveryResult("online"))
    second, _ = await create("second", query="another")
    monkeypatch.setattr(
        search_worker, "search_repository_metadata", lambda _: pytest.fail("provider")
    )
    await run(await search_jobs.claim_search())
    result = await read(second["id"])
    assert result.execution_status == "failed" and result.outcome == "incomplete"
    assert result.errors[0].code == "api_quota_exceeded" and result.errors[0].retry_at
    with pytest.raises(QuotaExceeded):
        await create("retry", retry_search_id=second["id"])
    assert (await read(session["id"])).outcome == "empty"


async def test_commit_ack_loss_does_not_repeat_provider_or_downstream_quota(database, monkeypatch):
    await database.init_database()
    calls = []
    original = search_jobs.complete_discovery

    def discover(query):
        calls.append("provider")
        return RepositorySearchResponse(results=[provider_result()])

    async def save(job, result):
        value = await original(job, result)
        calls.append("persist")
        if calls.count("persist") == 1:
            raise psycopg.OperationalError("lost commit acknowledgement")
        return value

    monkeypatch.setattr(search_worker, "search_repository_metadata", discover)
    monkeypatch.setattr(search_worker, "complete_discovery", save)
    monkeypatch.setattr(
        search_worker, "persist_with_retry", partial(persist_with_retry, initial_delay=0.001)
    )
    await admit(query="health")
    await run(await search_jobs.claim_search())
    assert calls == ["provider", "persist", "persist"]
    assert len(await rows("SELECT * FROM repository_candidates")) == 1
    quota = await rows(
        "SELECT * FROM api_rate_limits WHERE operation = 'repository_classification'"
    )
    assert quota[0]["request_count"] == 1


async def test_failed_downstream_admission_publishes_nothing(database, monkeypatch):
    await database.init_database()
    session, _ = await admit(query="health")
    job = await search_jobs.claim_search()

    async def reject(*args, **kwargs):
        raise QuotaExceeded(10)

    monkeypatch.setattr(search_jobs, "reserve_work", reject)
    with pytest.raises(QuotaExceeded):
        await search_jobs.complete_discovery(
            job,
            DiscoveryResult(
                "online",
                candidates=[provider_result()],
            ),
        )
    assert not await rows("SELECT * FROM repository_candidates")
    assert (await read(session["id"])).execution_status == "running"


async def test_reinitialization_does_not_reschedule_completed_inline_search(database):
    await database.init_database()
    item = await candidate(database)
    await database.complete_search_session(item["search_session_id"], "alice", origin="online")
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    await database.init_database()
    assert await search_jobs.claim_search() is None
    assert (await rows("SELECT execution_mode FROM search_sessions"))[0][
        "execution_mode"
    ] == "inline"
    assert (await stored_candidate(item["id"], "alice"))["title"] == "Mortality"
    assert not await rows("SELECT * FROM api_commands")


async def test_startup_consumes_queued_discovery_without_http(database, monkeypatch):
    from app.lifecycle import lifespan
    from app.main import app

    await database.init_database()
    session, _ = await admit(query="health")
    await database.close_database_pool()
    monkeypatch.setenv("API_AUTH_MODE", "local")
    monkeypatch.setattr(
        search_worker, "search_repository_metadata", lambda _: RepositorySearchResponse(results=[])
    )
    try:
        async with lifespan(app):

            async def finished():
                return (await read(session["id"])).execution_status == "finished"

            await wait_until(finished)
            assert (await read(session["id"])).outcome == "empty"
    finally:
        await database.open_database_pool()


async def test_unsupported_search_access_mode_is_rejected(database):
    await database.init_database()
    with pytest.raises(ValueError, match="Unsupported access mode"):
        await search_jobs.admit_search(
            "alice", "unsupported-mode", query="health", access_mode="unknown", client_key=None,
        )
    assert not await rows("SELECT * FROM search_sessions")


async def test_http_admission_is_idempotent_atomic_owned_and_does_no_provider_work(
    database,
    api,
    monkeypatch,
):
    await database.init_database()
    monkeypatch.setattr(
        search_worker, "search_repository_metadata", lambda _: pytest.fail("provider")
    )
    async with browser(api) as client:
        assert (
            await client.post("/collector/searches", json={"query": "health"})
        ).status_code == 401
        assert (
            await client.post("/collector/searches", headers=headers(), json={"query": "health"})
        ).status_code == 422
        h = {**headers(), "Idempotency-Key": "same-command"}
        responses = await asyncio.gather(
            *[
                client.post("/collector/searches", headers=h, json={"query": "health"})
                for _ in range(6)
            ]
        )
        assert sorted(r.status_code for r in responses) == [200] * 5 + [202]
        ids = {r.json()["search_id"] for r in responses}
        assert len(ids) == 1
        sid = ids.pop()
        assert responses[0].json()["execution_status"] == "queued"
        assert responses[0].headers["location"] == f"/collector/searches/{sid}/progress"
        assert (
            await client.post("/collector/searches", headers=h, json={"query": "different"})
        ).status_code == 409
        for extra in ({"owner_id": "bob"}, {"client_key": "fake"}, {"access_mode": "local"}):
            assert (
                await client.post(
                    "/collector/searches", headers=h, json={"query": "health", **extra}
                )
            ).status_code == 422
        latest = await client.get("/collector/searches/latest", headers=headers())
        assert latest.json()["search_id"] == sid
        assert latest.json()["polling_required"] and latest.json()["outcome"] is None
        assert latest.json()["origin"] is None
        for path in (f"/collector/searches/{sid}/progress", "/collector/searches/latest"):
            assert (await client.get(path, headers=headers("bob"))).status_code == 404
        other = await client.post(
            "/collector/searches",
            headers={**headers("bob"), "Idempotency-Key": "same-command"},
            json={"query": "health"},
        )
        assert other.status_code == 202 and other.json()["search_id"] != sid
    assert len(await rows("SELECT * FROM search_sessions")) == 2
    quotas = await rows("SELECT * FROM api_rate_limits WHERE owner_id = 'alice'")
    assert len(quotas) == 1 and quotas[0]["request_count"] == 1
