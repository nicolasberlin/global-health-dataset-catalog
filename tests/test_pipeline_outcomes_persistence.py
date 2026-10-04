"""New conclusions and diagnostics survive real PostgreSQL transactions and recovery."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime

import pytest
from app import classification_worker
from app.db import classification_votes as votes
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.connection import _fetchall, _require_database_pool
from app.routes.collector import _candidate_with_collection
from test_classifier_factory import MODELS, _response
from test_collection_workflow import candidate_for, decision
from test_pipeline_outcomes import collect
from test_search_progress import read
from test_vote_persistence import transport  # noqa: F401

from collector.diagnostics import Diagnostic
from collector.storage.models import CollectionReport, CollectionResult

pytestmark = pytest.mark.anyio


async def query(sql, parameters=None):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, sql, parameters)


async def test_local_result_count_survives_reopening_database(database):
    await database.init_database()
    search = await database.create_search_session("mortality", "alice")
    await database.complete_search_session(
        search["id"], "alice", origin="database", local_result_count=2
    )
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    result = await read(search["id"])
    assert result.execution_status == "finished" and result.outcome == "results"
    assert result.local_result_count == 2 and result.items == []


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["unconfirmed"], "incomplete"),
        (["restricted"], "incomplete"),
        (["unavailable"], "empty"),
        (["unconfirmed", "available"], "results"),
    ],
)
async def test_report_conclusion_reaches_individual_and_grouped_reads(database, statuses, expected):
    await database.init_database()
    candidate = await candidate_for(database)
    sid = candidate["search_session_id"]
    await database.complete_search_session(sid, "alice", origin="online")
    completion = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job_id = completion.collection.job["id"]
    await database.mark_collection_job_running(job_id)
    await database.complete_collection_job(job_id, collect(statuses))
    result = await read(sid)
    single = await _candidate_with_collection(completion.candidate, "alice")
    assert result.outcome == expected
    assert result.execution_status == "finished" and not result.polling_required
    assert single.automatic_collection == result.items[0].automatic_collection
    assert single.automatic_collection.outcome == expected
    assert bool(single.automatic_collection.errors) == (expected == "incomplete")


async def test_incomplete_report_can_commit_usable_datasets(database):
    await database.init_database()
    candidate = await candidate_for(database)
    await database.complete_search_session(candidate["search_session_id"], "alice", origin="online")
    completion = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job_id = completion.collection.job["id"]
    await database.mark_collection_job_running(job_id)
    result = collect(["available"])
    result = replace(
        result,
        report=replace(
            result.report,
            verification_complete=False,
            errors=[Diagnostic("verification_unconfirmed", "validation")],
        ),
    )
    await database.complete_collection_job(job_id, result)
    progress = await read(candidate["search_session_id"])
    assert progress.outcome == "incomplete"
    assert progress.items[0].automatic_collection.dataset_ids
    assert (await database.get_collection_job(job_id))["saved_count"] == 1


async def test_worker_preserves_failed_voter_cause_and_attempt(database, transport):  # noqa: F811
    await database.init_database()
    candidate = await candidate_for(database)
    await database.complete_search_session(candidate["search_session_id"], "alice", origin="online")
    claimed = await database.get_repository_candidate(candidate["id"], "alice")
    claimed["owner_id"] = "alice"

    def request(req, timeout):
        if json.loads(req.data)["model"] == MODELS[2]:
            raise TimeoutError("private-secret")
        return _response("repository", False)

    transport(request)
    with ThreadPoolExecutor(1) as executor:
        await classification_worker._run_classification(claimed, executor)
    progress = await read(candidate["search_session_id"])
    assert (progress.execution_status, progress.outcome) == ("failed", "incomplete")
    diagnostic = progress.items[0].errors[0]
    assert diagnostic.code == "llm_timeout" and diagnostic.voter_id
    assert diagnostic.attempt == 1 and diagnostic.max_attempts is None
    assert "private-secret" not in progress.model_dump_json()
    saved = await query("SELECT * FROM classification_votes WHERE status = 'error'")
    assert saved[0]["errors"][0]["code"] == "llm_timeout"
    assert len(await query("SELECT * FROM classification_votes WHERE status = 'succeeded'")) == 2


async def test_restart_retry_and_old_write_preserve_error_contract(database):
    await database.init_database()
    candidate = await candidate_for(database)
    completion = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job_id = completion.collection.job["id"]
    running = await database.mark_collection_job_running(job_id)
    old_version = datetime.fromisoformat(running["updated_at"])
    await database.mark_interrupted_collection_jobs_error()
    job = await database.get_collection_job(job_id)
    assert job["errors"][0]["code"] == "processing_interrupted"
    assert job["outcome"] == "incomplete"
    await retry_collection_job_for_owner(job_id, "alice")
    new = await database.claim_pending_collection_job()
    assert new["errors"] == [] and new["outcome"] is None
    assert (
        await database.mark_collection_job_error(
            job_id,
            "stale",
            errors=[Diagnostic("llm_timeout", "classification").to_dict()],
            expected_updated_at=old_version,
        )
        is None
    )
    assert (await database.get_collection_job(job_id))["errors"] == []


async def test_migration_preserves_old_data_without_claiming_complete_outcomes(database):
    await database.init_database()
    candidate = await candidate_for(database)
    await database.complete_search_session(candidate["search_session_id"], "alice", origin="online")
    await database.fail_candidate_classification(candidate["id"], "alice", "old private error")
    job = await database.create_collection_job("https://example.org/old")
    await database.mark_collection_job_running(job["id"])
    snapshot = {"configuration": [{"voter_id": "a"}], "payload": {}}
    run = await votes.prepare_vote_run(snapshot, job_id=job["id"])
    vote = await votes.claim_vote(run, "a", job_id=job["id"])
    await votes.finish_vote(
        run, "a", vote["attempt_token"], response={"accepted": False}, job_id=job["id"]
    )
    await database.complete_collection_job(
        job["id"],
        CollectionResult(
            report=CollectionReport(verification_complete=True),
        ),
    )
    async with _require_database_pool().connection() as connection:
        for table in (
            "search_sessions",
            "repository_candidates",
            "collection_jobs",
            "classification_votes",
        ):
            await connection.execute(f"ALTER TABLE {table} DROP COLUMN errors")
        await connection.execute(
            "ALTER TABLE search_sessions DROP COLUMN local_result_count, "
            "DROP COLUMN discovery_complete"
        )
        await connection.execute("ALTER TABLE collection_jobs DROP COLUMN outcome")
        await connection.execute("DELETE FROM schema_migrations WHERE version = 7")
    await database.init_database()
    await database.init_database()
    assert (await database.get_collection_job(job["id"]))["outcome"] == "incomplete"
    progress = await read(candidate["search_session_id"])
    assert progress.outcome == "incomplete"
    assert progress.items[0].errors[0].code == "legacy_unknown"
    assert (await database.get_repository_candidate(candidate["id"], "alice"))["error"] == (
        "old private error"
    )
    saved = await query("SELECT * FROM classification_votes")
    assert saved[0]["response"] == {"accepted": False}
    assert saved[0]["attempts"] == 1
    session = (await query("SELECT * FROM search_sessions"))[0]
    assert session["discovery_complete"] is None and session["local_result_count"] is None


async def test_vote_storage_failure_is_not_a_model_vote_failure(
    database, transport, monkeypatch,  # noqa: F811
):
    from app import vote_store

    await database.init_database()
    candidate = await candidate_for(database)
    claimed = await database.get_repository_candidate(candidate["id"], "alice")
    claimed["owner_id"] = "alice"
    calls = []

    def request(req, timeout):
        calls.append(req)
        return _response("repository", True)

    async def broken_save(*args, **kwargs):
        raise RuntimeError("SQL private-secret")

    transport(request)
    monkeypatch.setattr(vote_store, "finish_vote", broken_save)
    with ThreadPoolExecutor(1) as executor:
        await classification_worker._run_classification(claimed, executor)
    stored = await database.get_repository_candidate(candidate["id"], "alice")
    assert stored["classification_status"] == "error"
    assert stored["errors"][0]["code"] == "persistence_failed"
    assert len(calls) == 3
    assert "private-secret" not in str(stored["errors"])
