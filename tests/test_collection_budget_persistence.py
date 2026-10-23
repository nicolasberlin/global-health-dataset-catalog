"""Each planned attempt gets a deadline; replay and interruption cannot extend it."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from app.db import task_retries
from app.db.connection import _require_database_pool
from app.db.schema import CURRENT_SCHEMA_VERSION
from helpers.workflows import candidate_for, decision

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


async def test_automatic_retry_starts_fresh_budget_only_when_claimed(database, monkeypatch):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "300")
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
    assert row["collection_deadline_at"] is None
    await database.mark_interrupted_collection_jobs_error()
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    await sql("UPDATE collection_jobs SET next_retry_at = NOW() - INTERVAL '1 second'")
    resumed = await database.claim_pending_collection_job()
    deadline = datetime.fromisoformat(resumed["collection_deadline_at"])
    assert deadline - datetime.fromisoformat(resumed["updated_at"]) == timedelta(seconds=300)
    assert resumed["collection_deadline_at"] > job["collection_deadline_at"]
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["retry_round"] == 1


@pytest.mark.parametrize("legacy", [False, True])
async def test_interruption_without_new_attempt_does_not_extend_deadline(
    database, monkeypatch, legacy
):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "300")
    await database.init_database()
    pending = await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    assert job["id"] == pending["id"]
    await database.mark_interrupted_collection_jobs_error()
    interrupted = await database.get_collection_job(job["id"])
    assert interrupted["collection_deadline_at"] == job["collection_deadline_at"]
    # Recover the same admitted attempt, without scheduling or a manual retry command.
    await sql("UPDATE collection_jobs SET status = 'pending' WHERE id = %s", (job["id"],))
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "3600")
    resumed = await (
        database.mark_collection_job_running(job["id"])
        if legacy else database.claim_pending_collection_job()
    )
    assert resumed["collection_deadline_at"] == job["collection_deadline_at"]
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["retry_round"] == 0


@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_retry_due_can_fall_after_previous_attempt_deadline(database, monkeypatch, offset):
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
    assert actual
    assert errors[0].retry_at == due.isoformat()
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["collection_deadline_at"] is None
    assert row["status"] == "pending" and row["retry_round"] == 1
    assert row["next_retry_at"] == due


async def test_retry_after_is_not_shortened_by_previous_attempt_budget(database, monkeypatch):
    monkeypatch.setenv("COLLECTION_MAX_DURATION_SECONDS", "5")
    await database.init_database()
    await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    deadline = datetime.fromisoformat(job["collection_deadline_at"])
    due = deadline + timedelta(seconds=30)
    scheduled, errors = await task_retries.schedule_llm_retry(
        job["id"],
        datetime.fromisoformat(job["updated_at"]),
        [Diagnostic("llm_rate_limited", "classification", retry_at=due.isoformat())],
        collection=True,
    )
    assert scheduled and errors[0].retry_at == due.isoformat()
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["next_retry_at"] == due and row["collection_deadline_at"] is None
    assert row["retry_round"] == 1
    assert await database.claim_pending_collection_job() is None


async def test_exhausted_attempt_cannot_gain_budget_by_scheduling_retry(database):
    await database.init_database()
    await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    await sql("UPDATE collection_jobs SET collection_deadline_at = NOW() - INTERVAL '1 second'")
    scheduled, errors = await task_retries.schedule_llm_retry(
        job["id"], datetime.fromisoformat(job["updated_at"]),
        [Diagnostic("llm_timeout", "classification")], collection=True,
    )
    assert not scheduled
    assert {item.code for item in errors} == {"llm_timeout", "collection_budget_exhausted"}
    assert all(item.recovery != "automatic" for item in errors)
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["status"] == "running" and row["retry_round"] == 0
    assert row["collection_deadline_at"] is not None and row["next_retry_at"] is None


async def test_retry_limit_does_not_clear_current_attempt_deadline(database, monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    await database.init_database()
    await database.create_collection_job("https://example.org/dataset")
    job = await database.claim_pending_collection_job()
    await sql("UPDATE collection_jobs SET retry_round = 1")
    scheduled, errors = await task_retries.schedule_llm_retry(
        job["id"], datetime.fromisoformat(job["updated_at"]),
        [Diagnostic("llm_timeout", "classification", attempt=2)], collection=True,
    )
    assert not scheduled and all(item.recovery != "automatic" for item in errors)
    row = (await sql("SELECT * FROM collection_jobs WHERE id = %s", (job["id"],)))[0]
    assert row["status"] == "running" and row["retry_round"] == 1
    assert row["collection_deadline_at"] == datetime.fromisoformat(job["collection_deadline_at"])
    assert row["next_retry_at"] is None


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


async def test_reinitialization_preserves_jobs_and_starts_pending_budget_on_claim(database):
    await database.init_database()
    await database.create_collection_job("https://example.org/completed")
    completed = await database.claim_pending_collection_job()
    await database.mark_collection_job_done(
        completed["id"], 0, CollectionReport(verification_complete=True)
    )
    completed_deadline = completed["collection_deadline_at"]
    pending = await database.create_collection_job("https://example.org/pending")
    assert pending["collection_deadline_at"] is None
    await database.init_database()
    await database.init_database()
    completed = await database.get_collection_job(completed["id"])
    assert completed["status"] == "done" and completed["outcome"] == "empty"
    assert completed["collection_deadline_at"] == completed_deadline
    claimed = await database.claim_pending_collection_job()
    assert claimed["id"] == pending["id"] and claimed["collection_deadline_at"] is not None
    assert (await sql("SELECT max(version) AS version FROM schema_migrations"))[0]["version"] == (
        CURRENT_SCHEMA_VERSION
    )
