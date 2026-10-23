"""New conclusions and diagnostics survive real PostgreSQL transactions and recovery."""

import asyncio
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial

import pytest
from app.db.connection import _fetchall, _require_database_pool
from app.workers import classification as classification_worker
from helpers.classification import MODELS
from helpers.classification import response as _response
from helpers.collection import collect
from helpers.inspection import stored_candidate
from helpers.workflows import candidate_for, decision, read

from collector.diagnostics import Diagnostic, PersistenceFailure

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


async def test_worker_preserves_failed_voter_cause_and_attempt(database, transport):
    await database.init_database()
    candidate = await candidate_for(database)
    await database.complete_search_session(candidate["search_session_id"], "alice", origin="online")
    claimed = await stored_candidate(candidate["id"], "alice")
    claimed["owner_id"] = "alice"

    def request(req, timeout):
        if json.loads(req.data)["model"] == MODELS[2]:
            raise TimeoutError("private-secret")
        return _response("repository", False)

    transport(request)
    with ThreadPoolExecutor(1) as executor:
        await classification_worker._run_classification(claimed, executor)
    progress = await read(candidate["search_session_id"])
    assert (progress.execution_status, progress.outcome) == ("waiting_retry", None)
    diagnostic = progress.items[0].errors[0]
    assert diagnostic.code == "llm_timeout" and diagnostic.voter_id
    assert diagnostic.attempt == 1 and diagnostic.max_attempts == 3
    assert "private-secret" not in progress.model_dump_json()
    saved = await query("SELECT * FROM classification_votes WHERE status = 'error'")
    assert saved[0]["errors"][0]["code"] == "llm_timeout"
    assert len(await query("SELECT * FROM classification_votes WHERE status = 'succeeded'")) == 2


async def test_vote_storage_failure_is_not_a_model_vote_failure(
    database, transport, monkeypatch,
):
    from app import vote_store

    await database.init_database()
    candidate = await candidate_for(database)
    claimed = await stored_candidate(candidate["id"], "alice")
    claimed["owner_id"] = "alice"
    calls = []

    def request(req, timeout):
        calls.append(req)
        return _response("repository", True)

    async def broken_save(*args, **kwargs):
        # A fenced/superseded claim is a terminal persistence condition. Other
        # SQL failures now retain the computed response until storage is repaired.
        raise PersistenceFailure("SQL private-secret")

    transport(request)
    monkeypatch.setattr(vote_store, "finish_vote", broken_save)
    with ThreadPoolExecutor(1) as executor:
        await classification_worker._run_classification(claimed, executor)
    stored = await stored_candidate(candidate["id"], "alice")
    assert stored["classification_status"] == "error"
    assert stored["errors"][0]["code"] == "persistence_failed"
    assert len(calls) == 3
    assert "private-secret" not in str(stored["errors"])


async def test_repaired_vote_storage_keeps_model_responses_without_new_invocations(
    database, transport, monkeypatch,
):
    from app import vote_store

    await database.init_database()
    candidate = await candidate_for(database)
    claimed = await stored_candidate(candidate["id"], "alice")
    claimed["owner_id"] = "alice"
    calls, saves = Counter(), Counter()
    actual_finish = vote_store.finish_vote

    def request(req, timeout):
        calls[json.loads(req.data)["model"]] += 1
        return _response("repository", True)

    async def repaired_save(run_id, voter_id, token, **kwargs):
        saves[voter_id] += 1
        if saves[voter_id] == 1:
            raise RuntimeError("SQL private-secret")
        return await actual_finish(run_id, voter_id, token, **kwargs)

    transport(request)
    monkeypatch.setattr(vote_store, "finish_vote", repaired_save)
    monkeypatch.setattr(vote_store, "persist_with_retry",
                        partial(vote_store.persist_with_retry, initial_delay=0))
    with ThreadPoolExecutor(1) as executor:
        await asyncio.wait_for(classification_worker._run_classification(claimed, executor), 3)
    stored = await stored_candidate(candidate["id"], "alice")
    assert stored["classification_status"] == "accepted" and stored["errors"] == []
    assert calls == Counter({model: 1 for model in MODELS})
    assert list(saves.values()) == [2, 2, 2]
    saved = await query("SELECT status, attempts, response FROM classification_votes")
    assert len(saved) == 3
    assert all(vote["status"] == "succeeded" and vote["attempts"] == 1 and vote["response"]
               for vote in saved)
