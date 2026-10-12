from datetime import datetime

import pytest
from app.db.classification_votes import (
    claim_vote,
    finish_vote,
    prepare_vote_run,
    read_collection_vote_history,
)
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.collection_traces import read_collection_trace, write_collection_trace
from app.db.connection import _fetchall, _require_database_pool
from httpx import ASGITransport, AsyncClient
from schema_helpers import restore_schema_eleven
from test_classification_workflow import api, headers  # noqa: F401
from test_collection_workflow import candidate_for, decision

from collector.storage.models import CollectionReport, CollectionResult

pytestmark = pytest.mark.anyio


async def claimed(database):
    await database.init_database()
    candidate = await candidate_for(database)
    accepted = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job = await database.claim_pending_collection_job()
    assert job["id"] == accepted.collection.job["id"]
    return job, datetime.fromisoformat(job["updated_at"])


def observation(status="succeeded"):
    return {
        "method": "browser",
        "status": status,
        "http_status": 200,
        "requested_url": "https://example.org/data?token=secret",
        "final_url": "https://example.org/data?fileId=1&token=secret",
        "html": "DO NOT STORE",
        "cookies": {"auth": "DO NOT STORE"},
        "code": "repository_metadata_invalid",
        "failure_phase": "normalize",
        "reason": "DO NOT STORE",
        "checks": [
            {
                "resource_key": "file:1",
                "url": "https://example.org/file?token=secret",
                "format": "CSV",
                "status": "available",
                "http_status": 206,
            }
        ],
    }


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


async def test_final_coverage_and_protected_diagnostic_export(database, api):  # noqa: F811
    job, version = await claimed(database)
    scope = {"job_id": job["id"], "expected_updated_at": version}
    run = await prepare_vote_run(
        {"configuration": [{"voter_id": "apertus", "body": {"model": "Apertus Meditron"}}]},
        **scope,
    )
    vote = await claim_vote(run, "apertus", **scope)
    await finish_vote(run, "apertus", vote["attempt_token"], error="Invalid dataset_signals.",
                      **scope)
    # Simulate a subsequent authorized cycle; retain the failed attempt.
    async with _require_database_pool().connection() as connection:
        await connection.execute(
            "UPDATE collection_jobs SET retry_cycle = gen_random_uuid() WHERE id = %s",
            (job["id"],),
        )
    vote = await claim_vote(run, "apertus", **scope)
    await finish_vote(run, "apertus", vote["attempt_token"], response={"accepted": True},
                      **scope)
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
        assert history[0]["error"] == "Invalid dataset_signals."
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


async def test_migration_from_eleven_preserves_existing_job(database):
    job, version = await claimed(database)
    await database.complete_collection_job(
        job["id"],
        CollectionResult([], report=CollectionReport(verification_complete=True)),
        expected_updated_at=version,
    )
    await restore_schema_eleven()
    await database.init_database()
    stored = await database.get_collection_job(job["id"])
    assert stored["status"] == "done" and stored["outcome"] == "empty"
    assert (await read_collection_trace(job["id"], "alice"))["method_attempts"] == []


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
    assert history["attempts"][0]["error"] == "Vote replaced by a new retry cycle."
    assert first["attempts"] == 1
    assert await read_collection_vote_history(child["id"], "bob") is None
