from datetime import datetime

import pytest
from app.db.classification_votes import (
    claim_vote,
    finish_vote,
    prepare_vote_run,
    read_collection_vote_history,
)
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.collection_traces import read_collection_trace, safe_url, write_collection_trace
from app.db.connection import _fetchall, _require_database_pool
from helpers.workflows import claimed, headers, observation
from httpx import ASGITransport, AsyncClient

from collector.storage.models import CollectionReport, CollectionResult

pytestmark = pytest.mark.anyio


async def test_trace_upsert_does_not_change_claim_and_guards_stale_attempts(database):
    job, version = await claimed(database)
    assert await write_collection_trace(job["id"], version, 0, observation("running"))
    assert await write_collection_trace(job["id"], version, 0, observation())
    assert (await database.get_collection_job(job["id"]))["updated_at"] == job["updated_at"]
    trace = await read_collection_trace(job["id"], "alice")
    assert len(trace["method_attempts"]) == 1
    assert len(trace["method_attempts"][0]["checks"]) == 1
    assert trace["method_attempts"][0]["failure_phase"] == "normalize"
    assert trace["method_attempts"][0]["reason"] == (
        "The received metadata does not match the connector format."
    )
    assert "secret" not in str(trace) and "DO NOT STORE" not in str(trace)
    assert await read_collection_trace(job["id"], "bob") is None
    await database.complete_collection_job(
        job["id"],
        CollectionResult([], report=CollectionReport(verification_complete=True)),
        expected_updated_at=version,
    )
    retried = await retry_collection_job_for_owner(job["id"], "alice", idempotency_key="retry-test")
    assert retried["status"] == "pending"
    new_job = await database.claim_pending_collection_job()
    new_version = datetime.fromisoformat(new_job["updated_at"])
    assert not await write_collection_trace(job["id"], version, 1, observation())
    assert await write_collection_trace(job["id"], new_version, 0, observation())
    assert len((await read_collection_trace(job["id"], "alice"))["method_attempts"]) == 2
    replay = await retry_collection_job_for_owner(job["id"], "alice", idempotency_key="retry-test")
    assert replay["status"] == "running" and replay["updated_at"] == new_job["updated_at"]


async def test_final_coverage_and_protected_diagnostic_export(database, api):
    job, version = await claimed(database)
    scope = {"job_id": job["id"], "expected_updated_at": version}
    run = await prepare_vote_run(
        {"configuration": [{"voter_id": "apertus", "body": {"model": "Apertus Meditron"}}]},
        **scope,
    )
    vote = await claim_vote(run, "apertus", **scope)
    await finish_vote(
        run, "apertus", vote["attempt_token"], error="Invalid dataset_signals.", **scope
    )
    # Simulate a subsequent authorized cycle; retain the failed attempt.
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE collection_jobs SET retry_cycle = gen_random_uuid() WHERE id = %s",
            (job["id"],),
        )
    vote = await claim_vote(run, "apertus", **scope)
    await finish_vote(run, "apertus", vote["attempt_token"], response={"accepted": True}, **scope)
    await write_collection_trace(job["id"], version, 0, observation())
    coverage = {"checked": 1, "validated": 0, "limited": False}
    result = CollectionResult(
        [], report=CollectionReport(coverage=coverage, method_attempts=[observation()])
    )
    await database.complete_collection_job(job["id"], result, expected_updated_at=version)
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        path = f"/collector/collection-jobs/{job['id']}/diagnostics"
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=headers("bob"))).status_code == 404
        response = await client.get(path, headers=headers())
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["coverage"] == coverage
        history = response.json()["classification_history"]["attempts"]
        assert [a["status"] for a in history] == ["error", "succeeded"]
        assert "error" not in history[0]
        assert history[0]["errors"][0]["code"] == "processing_failed"
        assert history[0]["model"] == "Apertus Meditron"
        async with _require_database_pool().connection() as connection:
            rows = await _fetchall(
                connection, "SELECT id FROM search_sessions WHERE owner_id='alice'"
            )
        export = await client.get(
            f"/collector/searches/{rows[0]['id']}/diagnostics", headers=headers()
        )
        assert export.status_code == 200
        assert export.json()["document_type"] == "search_diagnostic_trace"
        assert export.json()["collections"][0]["method_attempts"][0]["method"] == "browser"
        assert export.json()["collections"][0]["classification_history"]["attempts"] == history
        assert len(export.json()["repository_classifications"]) == 1


async def test_reinitialization_preserves_completed_job(database):
    job, version = await claimed(database)
    await database.complete_collection_job(
        job["id"],
        CollectionResult([], report=CollectionReport(verification_complete=True)),
        expected_updated_at=version,
    )
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    stored = await database.get_collection_job(job["id"])
    assert stored["status"] == "done" and stored["outcome"] == "empty"
    assert (await read_collection_trace(job["id"], "alice"))["method_attempts"] == []


async def test_ipv6_diagnostic_urls_survive_storage_and_repeated_sanitization(database):
    job, version = await claimed(database)
    raw_url = "https://user:secret@[2001:db8::1]:8443/data?token=secret&id=123#private"
    expected = "https://[2001:db8::1]:8443/data?id=123"
    value = observation()
    value.update(requested_url=raw_url, final_url=raw_url)
    value["checks"] = [{"url": raw_url, "resource_key": raw_url, "status": "available"}]

    assert await write_collection_trace(job["id"], version, 0, value)
    trace = await read_collection_trace(job["id"], "alice")
    method = trace["method_attempts"][0]
    assert method["requested_url"] == method["final_url"] == expected
    assert method["checks"][0]["url"] == method["checks"][0]["resource_key"] == expected
    assert "secret" not in str(trace) and "private" not in str(trace)

    assert await write_collection_trace(job["id"], version, 0, method)
    reread = (await read_collection_trace(job["id"], "alice"))["method_attempts"][0]
    assert reread["requested_url"] == reread["final_url"] == expected
    assert reread["checks"] == method["checks"]
    assert safe_url("https://[invalid-address]/data") == ""
    assert safe_url("https://[2001:db8::1]:invalid/data") == ""


async def test_retry_lineage_history_requires_ownership_of_requested_job(database):
    job, version = await claimed(database)
    scope = {"job_id": job["id"], "expected_updated_at": version}
    run = await prepare_vote_run({"configuration": [{"voter_id": "a"}]}, **scope)
    first = await claim_vote(run, "a", **scope)
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE collection_jobs SET retry_cycle = gen_random_uuid() WHERE id = %s",
            (job["id"],),
        )
    second = await claim_vote(run, "a", **scope)
    assert second["attempts"] == 2
    await finish_vote(run, "a", second["attempt_token"], response={"accepted": True}, **scope)
    child = await database.create_collection_job("https://example.org/retry")
    assert await read_collection_vote_history(child["id"], "alice") is None
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE collection_jobs SET classification_root_id = %s WHERE id = %s",
            (job["id"], child["id"]),
        )
        await connection.execute(
            "INSERT INTO collection_job_candidates(job_id, candidate_id) "
            "SELECT %s, candidate_id FROM collection_job_candidates WHERE job_id = %s",
            (child["id"], job["id"]),
        )
    history = await read_collection_vote_history(child["id"], "alice")
    assert [a["status"] for a in history["attempts"]] == ["interrupted", "succeeded"]
    assert "error" not in history["attempts"][0]
    assert history["attempts"][0]["errors"][0]["code"] == "processing_interrupted"
    assert first["attempts"] == 1
    assert await read_collection_vote_history(child["id"], "bob") is None
