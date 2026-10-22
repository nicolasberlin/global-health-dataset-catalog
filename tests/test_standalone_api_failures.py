"""Failure/recovery contracts for an API consumer without any frontend process."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.db import search_jobs
from app.db.connection import _fetchall, _require_database_pool
from app.workers import collection as collection_worker
from app.workers import search as search_worker
from helpers.workflows import candidate_for, decision, headers
from httpx import ASGITransport, AsyncClient

from collector.diagnostics import Diagnostic, PipelineFailure
from collector.repository_search import RepositorySearchResponse
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    ValidationResult,
)

pytestmark = pytest.mark.anyio


def client_for(application):
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


async def sql(query, parameters=None):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, query, parameters)


async def persisted_state():
    tables = (
        "search_sessions", "repository_candidates", "collection_jobs", "api_commands",
        "api_rate_limits", "collected_datasets", "classification_runs",
    )
    return {
        table: sorted(await sql(f"SELECT * FROM {table}"), key=repr)
        for table in tables
    }


async def accepted_candidate(database):
    item = await candidate_for(database)
    await database.complete_search_session(item["search_session_id"], "alice", origin="online")
    completed = await database.complete_candidate_classification(item["id"], "alice", decision())
    return item, completed.collection.job


def owned_paths(item, job):
    sid, cid, jid = item["search_session_id"], item["id"], job["id"]
    return [
        ("GET", f"/collector/searches/{sid}/progress"),
        ("POST", f"/collector/searches/{sid}/retry"),
        ("GET", f"/collector/searches/{sid}/diagnostics"),
        ("GET", f"/collector/repository-candidates/{cid}"),
        ("POST", f"/collector/repository-candidates/{cid}/classify"),
        ("GET", f"/collector/repository-candidates/{cid}/classification-history"),
        ("GET", f"/collector/collection-jobs/{jid}"),
        ("POST", f"/collector/collection-jobs/{jid}/retry"),
        ("GET", f"/collector/collection-jobs/{jid}/classification-history"),
        ("GET", f"/collector/collection-jobs/{jid}/diagnostics"),
    ]


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid", "Bearer "])
async def test_invalid_credentials_cannot_read_or_enqueue_owned_work(
    database, api, authorization,
):
    await database.init_database()
    item, job = await accepted_candidate(database)
    before = await persisted_state()
    request_headers = {"Idempotency-Key": "unauthorized"}
    if authorization is not None:
        request_headers["Authorization"] = authorization
    async with client_for(api) as client:
        paths = owned_paths(item, job) + [
            ("GET", "/collector/searches/latest"),
            ("GET", "/collector/repository-analyses/latest"),
            ("POST", "/collector/searches"),
        ]
        for method, path in paths:
            options = {"json": {"query": "mortality"}} if path == "/collector/searches" else {}
            response = await client.request(method, path, headers=request_headers, **options)
            assert response.status_code == 401, (method, path, response.text)
    assert await persisted_state() == before


async def test_other_owner_cannot_probe_candidates_jobs_or_diagnostic_exports(
    database, api,
):
    await database.init_database()
    item, job = await accepted_candidate(database)
    missing_item = {"search_session_id": uuid4(), "id": uuid4()}
    before = await persisted_state()
    async with client_for(api) as client:
        for (method, owned), (_, missing) in zip(
            owned_paths(item, job), owned_paths(missing_item, {"id": 2_147_483_647})
        ):
            request_headers = {**headers("bob"), "Idempotency-Key": "other-owner"}
            denied = await client.request(method, owned, headers=request_headers)
            absent = await client.request(method, missing, headers=request_headers)
            assert denied.status_code == absent.status_code == 404, (method, owned)
            assert denied.json() == absent.json(), (method, owned)
        allowed = await client.get(
            f"/collector/searches/{item['search_session_id']}/diagnostics", headers=headers()
        )
        assert allowed.status_code == 200
        assert allowed.json()["context"]["search_id"] == str(item["search_session_id"])
    assert await persisted_state() == before


async def test_full_queue_rejects_without_receipt_and_replay_survives_pool_restart(
    database, api, monkeypatch,
):
    await database.init_database()
    monkeypatch.setenv("SEARCH_MAX_ACTIVE", "1")
    monkeypatch.setattr(
        search_worker, "search_repository_metadata", lambda _: RepositorySearchResponse()
    )
    alice = {**headers(), "Idempotency-Key": "accepted-command"}
    bob = {**headers("bob"), "Idempotency-Key": "initially-refused"}
    async with client_for(api) as client:
        first = await client.post("/collector/searches", headers=alice, json={"query": "malaria"})
        assert first.status_code == 202
        refused = await client.post("/collector/searches", headers=bob, json={"query": "diabetes"})
        assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
        assert len(await sql("SELECT * FROM api_commands")) == 1
        assert await sql("SELECT owner_id FROM api_rate_limits") == [{"owner_id": "alice"}]
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    async with client_for(api) as client:
        replays = await asyncio.gather(*[
            client.post("/collector/searches", headers=alice, json={"query": "malaria"})
            for _ in range(4)
        ])
        assert all(response.status_code == 200 for response in replays)
        assert all(
            response.json()["search_id"] == first.json()["search_id"] for response in replays
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            await search_worker._run_search(await search_jobs.claim_search(), executor)
        admitted = await client.post(
            "/collector/searches", headers=bob, json={"query": "diabetes"}
        )
        assert admitted.status_code == 202
        finished = await client.get(first.headers["location"], headers=headers())
        assert finished.json()["execution_status"] == "finished"
        assert finished.json()["outcome"] == "empty"
    assert len(await sql("SELECT * FROM api_commands")) == 2
    assert await sql("SELECT request_count FROM api_rate_limits ORDER BY owner_id") == [
        {"request_count": 1}, {"request_count": 1},
    ]


async def test_provider_timeout_is_safe_terminal_and_explicitly_recoverable_over_http(
    database, api, monkeypatch,
):
    await database.init_database()
    calls = []
    private_error = "test-only-password=not-a-real-secret"

    def discover(query):
        calls.append(query)
        if len(calls) == 1:
            raise PipelineFailure(
                private_error, diagnostics=[Diagnostic("repository_timeout", "search")]
            )
        return RepositorySearchResponse()

    monkeypatch.setattr(search_worker, "search_repository_metadata", discover)
    command = {**headers(), "Idempotency-Key": "timeout-command"}
    async with client_for(api) as client:
        created = await client.post(
            "/collector/searches", headers=command, json={"query": "mortality"}
        )
        assert created.status_code == 202
        with ThreadPoolExecutor(max_workers=1) as executor:
            await search_worker._run_search(await search_jobs.claim_search(), executor)
        progress = await client.get(created.headers["location"], headers=headers())
        failed = progress.json()
        assert progress.headers["cache-control"] == "no-store"
        assert failed["execution_status"] == "failed" and failed["outcome"] == "incomplete"
        assert not failed["polling_required"]
        assert failed["errors"][0]["code"] == "repository_timeout"
        assert private_error not in progress.text
        assert (await sql("SELECT error FROM search_sessions"))[0]["error"] == private_error
        exported = await client.get(
            f"/collector/searches/{failed['search_id']}/diagnostics", headers=headers()
        )
        assert exported.status_code == 200 and private_error not in exported.text
        assert exported.json()["summary"]["errors"][0]["code"] == "repository_timeout"
        replay = await client.post(
            "/collector/searches", headers=command, json={"query": "mortality"}
        )
        assert replay.status_code == 200 and replay.json()["execution_status"] == "failed"
        assert await search_jobs.claim_search() is None
        path = f"/collector/searches/{failed['search_id']}/retry"
        retried = await client.post(
            path, headers={**headers(), "Idempotency-Key": "timeout-recovery"}
        )
        assert retried.status_code == 202 and retried.json()["attempt"] == 2
        with ThreadPoolExecutor(max_workers=1) as executor:
            await search_worker._run_search(await search_jobs.claim_search(), executor)
        final = await client.get(created.headers["location"], headers=headers())
        assert final.json()["outcome"] == "empty" and final.json()["errors"] == []
    assert calls == ["mortality", "mortality"]


async def test_partial_collection_results_survive_restart_and_idempotent_http_retry(
    database, api, monkeypatch,
):
    await database.init_database()
    item, job = await accepted_candidate(database)
    resource_url = "https://repository.example.org/files/mortality.csv"
    dataset = CollectedDataset(
        dataset_url=str(job["source_url"]), title="Mortality", description="",
        publisher="", hosting_platform="", uploader="", dataset_signals={},
        distributions=[DistributionCandidate(url=resource_url, format="csv", probability=1)],
        validation_results=[ValidationResult(
            url=resource_url, final_url=resource_url, format="csv", ok=True, http_status=200,
        )],
    )
    results = iter([
        CollectionResult(
            datasets=[dataset], report=CollectionReport(
                discovered_count=2, analyzed_count=1, accepted_count=1,
                verification_complete=False,
                errors=[Diagnostic("collection_budget_exhausted", "collection")],
            ),
        ),
        CollectionResult(report=CollectionReport(verification_complete=True)),
    ])
    monkeypatch.setattr(collection_worker, "build_default_page_classifier", lambda **_: object())
    monkeypatch.setattr(
        collection_worker,
        "collect_repository_candidate_with_report",
        lambda *_, **__: next(results),
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        await collection_worker._run_collection_job(
            await database.claim_pending_collection_job(), executor
        )
    path = f"/collector/searches/{item['search_session_id']}/progress"
    async with client_for(api) as client:
        partial = (await client.get(path, headers=headers())).json()
        assert partial["execution_status"] == "finished" and partial["outcome"] == "incomplete"
        assert not partial["polling_required"] and len(partial["dataset_ids"]) == 1
        assert any(e["code"] == "collection_budget_exhausted" for e in partial["errors"])
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    async with client_for(api) as client:
        assert (await client.get(path, headers=headers())).json() == partial
        retry_path = f"/collector/collection-jobs/{job['id']}/retry"
        command = {**headers(), "Idempotency-Key": "partial-recovery"}
        replies = await asyncio.gather(*[
            client.post(retry_path, headers=command) for _ in range(4)
        ])
        assert all(response.status_code == 202 for response in replies)
        pending = (await client.get(path, headers=headers())).json()
        assert pending["polling_required"] and pending["dataset_ids"] == partial["dataset_ids"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            await collection_worker._run_collection_job(
                await database.claim_pending_collection_job(), executor
            )
        final = (await client.get(path, headers=headers())).json()
        assert final["execution_status"] == "finished" and final["outcome"] == "results"
        assert not final["polling_required"] and final["errors"] == []
        assert final["dataset_ids"] == partial["dataset_ids"]
        replay = await client.post(retry_path, headers=command)
        assert replay.status_code == 202 and replay.json()["job"]["status"] == "done"
        assert await database.claim_pending_collection_job() is None
        catalog = await client.get(
            "/collector/collected-datasets/by-id", params={"ids": final["dataset_ids"]}
        )
        assert catalog.status_code == 200
        assert catalog.json()["items"][0]["distributions"][0]["url"] == resource_url
    assert len(await sql("SELECT * FROM collected_datasets")) == 1
    assert len(await sql("SELECT * FROM collection_jobs")) == 1
    assert len(await sql("SELECT * FROM api_commands")) == 1
    assert await sql(
        "SELECT request_count FROM api_rate_limits WHERE operation = 'repository_classification'"
    ) == [{"request_count": 1}]
