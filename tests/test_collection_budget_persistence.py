"""Persisted collection deadlines span automatic retries, never manual cycles."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from app.db import task_retries
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.connection import _require_database_pool
from app.db.schema import CURRENT_SCHEMA_VERSION
from schema_helpers import restore_schema_nine
from test_collection_workflow import candidate_for, decision

from collector.diagnostics import Diagnostic
from collector.storage.models import CollectionReport

pytestmark = pytest.mark.anyio


async def sql(query, params=None):
    async with _require_database_pool().connection() as connection:
        cursor = await connection.execute(query, params)
        return await cursor.fetchall() if cursor.description else []


async def owned_job(database):
    candidate = await candidate_for(database)
    result = await database.complete_candidate_classification(candidate["id"], "alice", decision())
    return result.collection.job


@pytest.mark.parametrize("legacy", [False, True])
async def test_deadline_starts_at_first_claim(database, monkeypatch, legacy):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "37.5")
    await database.init_database()
    pending = await database.create_collection_job("https://example.org/dataset")
    assert pending["collection_deadline_at"] is None
    # Time spent queued must not consume the execution budget.
    await sql("UPDATE collection_jobs SET created_at = NOW() - INTERVAL '1 day'")
    job = await (
        database.mark_collection_job_running(pending["id"])
        if legacy
        else database.claim_pending_collection_job()
    )
    deadline = datetime.fromisoformat(job["collection_deadline_at"])
    assert deadline - datetime.fromisoformat(job["updated_at"]) == timedelta(seconds=37.5)
    assert (await database.get_collection_job(job["id"]))["collection_deadline_at"] == (
        job["collection_deadline_at"]
    )
    assert await database.claim_pending_collection_job() is None


async def test_automatic_retry_and_restart_preserve_deadline(database, monkeypatch):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "60")
    await database.init_database()
    await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    version = datetime.fromisoformat(job["updated_at"])
    scheduled, _ = await task_retries.schedule_llm_retry(
        job["id"], version, [Diagnostic("llm_timeout", "classification")], collection=True
    )
    assert scheduled
    assert await database.claim_pending_collection_job() is None
    # Replay after a lost commit acknowledgement must not spend another retry.
    assert (
        await task_retries.schedule_llm_retry(
            job["id"], version, [Diagnostic("llm_timeout", "classification")], collection=True
        )
    )[0]
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["retry_round"] == 1
    await database.mark_interrupted_collection_jobs_error()
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    # A configuration change during recovery must not extend an admitted cycle.
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "3600")
    await sql("UPDATE collection_jobs SET next_retry_at = NOW() - INTERVAL '1 second'")
    resumed = await database.claim_pending_collection_job()
    assert resumed["collection_deadline_at"] == job["collection_deadline_at"]


async def test_manual_retry_gets_new_budget_with_owner_and_replay_guards(database):
    await database.init_database()
    pending = await owned_job(database)
    job = await database.claim_pending_collection_job()
    assert pending["id"] == job["id"]
    await database.mark_collection_job_error(
        job["id"],
        "Collection timed out.",
        errors=[Diagnostic("collection_budget_exhausted", "collection").to_dict()],
    )
    assert await retry_collection_job_for_owner(job["id"], "bob", idempotency_key="retry") is None
    assert (await database.get_collection_job(job["id"]))["collection_deadline_at"] == (
        job["collection_deadline_at"]
    )
    first, second = await asyncio.gather(
        *(
            retry_collection_job_for_owner(job["id"], "alice", idempotency_key="retry")
            for _ in range(2)
        )
    )
    assert first["collection_deadline_at"] is None and second["collection_deadline_at"] is None
    resumed = await database.claim_pending_collection_job()
    assert resumed["collection_deadline_at"] > job["collection_deadline_at"]
    replay = await retry_collection_job_for_owner(job["id"], "alice", idempotency_key="retry")
    assert replay["collection_deadline_at"] == resumed["collection_deadline_at"]
    assert replay["status"] == "running"
    # An old worker cannot requeue this new cycle or modify its deadline.
    scheduled, _ = await task_retries.schedule_llm_retry(
        job["id"],
        datetime.fromisoformat(job["updated_at"]),
        [Diagnostic("llm_timeout", "classification")],
        collection=True,
    )
    assert scheduled
    assert (await database.get_collection_job(job["id"]))["collection_deadline_at"] == (
        resumed["collection_deadline_at"]
    )
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["retry_round"] == 0 and row["status"] == "running"


@pytest.mark.parametrize("offset,scheduled", [(-1, True), (0, False), (1, False)])
async def test_retry_due_must_be_strictly_before_deadline(database, monkeypatch, offset, scheduled):
    await database.init_database()
    await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    deadline = datetime.fromisoformat(job["collection_deadline_at"])
    due = deadline + timedelta(seconds=offset)
    error = Diagnostic(
        "llm_rate_limited", "classification", recovery="automatic", retry_at=due.isoformat()
    )
    monkeypatch.setattr(task_retries, "plan_retry", lambda *args, **kwargs: (due, [error]))
    actual, errors = await task_retries.schedule_llm_retry(
        job["id"], datetime.fromisoformat(job["updated_at"]), [error], collection=True
    )
    assert actual is scheduled
    assert errors[0].retry_at == due.isoformat()
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["collection_deadline_at"] == deadline
    assert row["status"] == ("pending" if scheduled else "running")
    if scheduled:
        assert row["next_retry_at"] == due
    else:
        assert errors[0].recovery == "manual"
        assert [error.code for error in errors] == [
            "llm_rate_limited",
            "collection_budget_exhausted",
        ]
        assert row["retry_round"] == 0 and row["next_retry_at"] is None


@pytest.mark.parametrize("expired", [False, True])
async def test_exhausted_llm_policy_adds_collection_diagnostic_only_after_expiration(
    database, expired
):
    await database.init_database()
    await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    if expired:
        await sql("UPDATE collection_jobs SET collection_deadline_at = NOW() - INTERVAL '1 second'")
    # Provider deadline lies beyond the LLM retry window, so the LLM policy refuses it itself.
    row = (await sql("SELECT NOW() AS now"))[0]
    retry_at = (row["now"] + timedelta(hours=1)).isoformat()
    scheduled, errors = await task_retries.schedule_llm_retry(
        job["id"],
        datetime.fromisoformat(job["updated_at"]),
        [Diagnostic("llm_rate_limited", "classification", retry_at=retry_at)],
        collection=True,
    )
    assert not scheduled and errors[0].retry_at == retry_at
    assert all(error.recovery != "automatic" for error in errors)
    assert any(error.code == "collection_budget_exhausted" for error in errors) is expired


async def test_migration_nine_preserves_jobs_and_starts_pending_budget_on_claim(database):
    await database.init_database()
    await database.create_collection_job("https://example.org/completed")
    completed = await database.claim_pending_collection_job()
    await database.mark_collection_job_done(
        completed["id"], 0, CollectionReport(verification_complete=True)
    )
    pending = await database.create_collection_job("https://example.org/pending")
    await restore_schema_nine()
    await database.init_database()
    await database.init_database()
    completed = await database.get_collection_job(completed["id"])
    assert completed["status"] == "done" and completed["outcome"] == "empty"
    assert completed["collection_deadline_at"] is None
    claimed = await database.claim_pending_collection_job()
    assert claimed["id"] == pending["id"] and claimed["collection_deadline_at"] is not None
    assert (await sql("SELECT max(version) AS version FROM schema_migrations"))[0]["version"] == (
        CURRENT_SCHEMA_VERSION
    )
