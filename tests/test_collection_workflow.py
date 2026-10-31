from __future__ import annotations

import asyncio
import threading
from uuid import UUID

import psycopg
import pytest
from app.db.classification.jobs import _complete_candidate_classification
from app.db.collection import reservations as job_store
from app.db.connection import _require_database_pool
from app.workers.collection import worker as collection_worker
from app.workers.runtime import persisted_workers
from helpers.inspection import stored_candidate
from helpers.workflows import SOURCE_URL, candidate_for, decision, rows, wait_until

from collector.storage.models import CollectionResult

pytestmark = pytest.mark.anyio


async def test_acceptance_and_shared_followup_commit_together(database):
    await database.init_database()
    alice = await candidate_for(database)
    bob = await candidate_for(database, "bob")
    first, second = await asyncio.gather(
        database.complete_candidate_classification(alice["id"], "alice", decision()),
        database.complete_candidate_classification(bob["id"], "bob", decision()),
    )
    assert first.candidate["classification_status"] == "accepted"
    assert second.candidate["classification_status"] == "accepted"
    assert first.collection.job["id"] == second.collection.job["id"]
    assert sum(result.collection.created for result in (first, second)) == 1
    assert len(await rows("SELECT id FROM collection_jobs")) == 1
    assert len(await rows("SELECT * FROM collection_job_candidates")) == 2


@pytest.mark.parametrize("reuse", [False, True])
async def test_association_failure_rolls_back_decision_and_reservation(
    database, monkeypatch, reuse
):
    await database.init_database()
    existing_id = None
    if reuse:
        alice = await candidate_for(database)
        existing = await database.complete_candidate_classification(
            alice["id"], "alice", decision()
        )
        existing_id = existing.collection.job["id"]
    bob = await candidate_for(database, "bob")

    async def invalid_association(connection, job_id, candidate_id):
        # A real SQL failure after the decision update and job insert/reuse.
        await connection.execute(
            "INSERT INTO collection_job_candidates (job_id, candidate_id) VALUES (%s, %s)",
            (job_id, UUID(int=0)),
        )

    monkeypatch.setattr(job_store, "_associate_job_candidate", invalid_association)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await database.complete_candidate_classification(bob["id"], "bob", decision())
    stored = await stored_candidate(bob["id"], "bob")
    assert stored["classification_status"] == "classifying"
    assert stored["classification"] is None
    assert await rows("SELECT id FROM collection_jobs") == ([{"id": existing_id}] if reuse else [])
    links = await rows("SELECT candidate_id FROM collection_job_candidates")
    assert len(links) == int(reuse)
    assert all(link["candidate_id"] != bob["id"] for link in links)


async def test_claims_are_unique_and_ignore_uncommitted_jobs(database):
    await database.init_database()
    candidate = await candidate_for(database)
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await _complete_candidate_classification(
                connection, candidate["id"], "alice", decision()
            )
            reservation = await job_store._reserve_repository_candidate_collection_job(
                connection,
                candidate["id"],
                "alice",
            )
            assert await database.claim_pending_collection_job() is None
    claims = await asyncio.gather(*(database.claim_pending_collection_job() for _ in range(4)))
    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 1
    assert claimed[0]["id"] == reservation.job["id"]
    assert claimed[0]["status"] == "running"
    assert claimed[0]["source_url"] == SOURCE_URL


async def test_startup_collects_persisted_pending_job_without_http_scheduling(
    database, monkeypatch
):
    from app.lifecycle import lifespan
    from app.main import app

    await database.init_database()
    candidate = await candidate_for(database)
    completed = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job_id = completed.collection.job["id"]
    interrupted = await database.create_collection_job("https://example.org/interrupted")
    await database.mark_collection_job_running(interrupted["id"])
    await database.close_database_pool()
    calls = []

    def collect(url, **kwargs):
        calls.append(url)
        return CollectionResult()

    monkeypatch.setattr(collection_worker, "collect_repository_candidate_with_report", collect)
    monkeypatch.setenv("API_AUTH_MODE", "local")
    monkeypatch.setenv("COLLECTION_MAX_CONCURRENCY", "1")
    try:
        async with lifespan(app):

            async def done():
                return (await database.get_collection_job(job_id))["status"] == "done"

            await wait_until(done)
            assert (await database.get_collection_job(interrupted["id"]))["status"] == "error"
            assert calls == [SOURCE_URL]
    finally:
        # Restore the pool expected by the database fixture's teardown.
        await database.open_database_pool()


async def test_busy_workers_leave_excess_jobs_pending_and_drain_on_shutdown(database, monkeypatch):
    await database.init_database()
    jobs = [await database.create_collection_job(f"https://example.org/{i}") for i in range(3)]
    release = threading.Event()
    started = []

    def collect(url, **kwargs):
        started.append(url)
        assert release.wait(timeout=5)
        return CollectionResult()

    monkeypatch.setattr(collection_worker, "collect_source_with_report", collect)
    manager = persisted_workers(
        collection_worker.CollectionWorker(), concurrency=2, poll_interval=0.01
    )
    await manager.__aenter__()
    closing = None
    try:

        async def two_running():
            records = await rows("SELECT status FROM collection_jobs")
            return sum(row["status"] == "running" for row in records) == 2 and len(started) == 2

        await wait_until(two_running)
        assert (await database.get_collection_job(jobs[2]["id"]))["status"] == "pending"
        closing = asyncio.create_task(manager.__aexit__(None, None, None))
        await asyncio.sleep(0)
        assert not closing.done()
    finally:
        release.set()
        if closing is None:
            closing = asyncio.create_task(manager.__aexit__(None, None, None))
        await asyncio.wait_for(closing, timeout=5)
    assert [
        row["status"] for row in await rows("SELECT status FROM collection_jobs ORDER BY id")
    ] == [
        "done",
        "done",
        "pending",
    ]
    assert len(started) == 2


@pytest.mark.parametrize("failure_stage", ["collect", "finalize"])
async def test_worker_records_error_and_continues_to_next_job(database, monkeypatch, failure_stage):
    await database.init_database()
    first = await database.create_collection_job("https://example.org/fail")
    second = await database.create_collection_job("https://example.org/pass")
    real_complete = collection_worker.complete_collection_job

    def collect(url, **kwargs):
        if failure_stage == "collect" and url.endswith("fail"):
            raise RuntimeError("test collection failure")
        return CollectionResult()

    async def complete(job_id, result, **kwargs):
        if failure_stage == "finalize" and job_id == first["id"]:
            raise RuntimeError("test persistence failure")
        return await real_complete(job_id, result, **kwargs)

    monkeypatch.setattr(collection_worker, "collect_source_with_report", collect)
    monkeypatch.setattr(collection_worker, "complete_collection_job", complete)
    async with persisted_workers(
        collection_worker.CollectionWorker(), concurrency=1, poll_interval=0.01
    ):

        async def done():
            return (await database.get_collection_job(second["id"]))["status"] == "done"

        await wait_until(done)
    failed = await database.get_collection_job(first["id"])
    assert failed["status"] == "error"
    assert "test " in failed["error"]
