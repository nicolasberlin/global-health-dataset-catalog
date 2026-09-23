from __future__ import annotations

import asyncio
import threading
from uuid import UUID

import psycopg
import pytest
from app import collection_worker
from app.db import collection_jobs as job_store
from app.db.connection import _fetchall, _require_database_pool
from app.db.repository_candidates import _complete_candidate_classification
from app.routes.collector import classify_repository_result
from app.security import APIPrincipal
from fastapi import Response

from collector.classification.repository import RepositoryClassification
from collector.repository_search import RepositorySearchResult
from collector.storage.models import CollectionResult

pytestmark = pytest.mark.anyio
SOURCE_URL = "https://repository.example.org/mortality"


def decision(accepted=True):
    label = "relevant" if accepted else "not_relevant"
    return RepositoryClassification(
        relevance_label=label,
        reason="Test decision.",
        ensemble={
            "votes_required": 2,
            "minimum_successful_votes": 3,
            "successful_votes": 3,
            "failed_votes": 0,
            "accepted_votes": 3 if accepted else 0,
            "decision": "accepted" if accepted else "rejected",
            "decision_reason": "enough_accept_votes" if accepted else "rejected_by_majority",
            "decision_voter_ids": ["a", "b", "c"],
            "failures": [],
            "voters": [
                {
                    "voter_id": voter,
                    "accepted": accepted,
                    "relevance_label": label,
                    "reason": "Test decision.",
                    "missing_information": [],
                }
                for voter in ("a", "b", "c")
            ],
        },
    )


async def _start_candidate(database, candidate_id, owner_id, *, retry=False):
    queued = await database.enqueue_candidate_classification(candidate_id, owner_id, retry=retry)
    if queued is None:
        return None
    return await database.claim_candidate_classification()


async def candidate_for(database, owner="alice", url=SOURCE_URL):
    session = await database.create_search_session("mortality", owner)
    candidates = await database.save_repository_candidates(
        session["id"],
        owner,
        [RepositorySearchResult(title="Mortality", url=url, source="DataCite")],
    )
    candidate = candidates[0]
    await _start_candidate(database, candidate["id"], owner)
    return candidate


async def rows(query):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, query)


async def wait_until(check):
    async def poll():
        while not await check():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=5)


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
    stored = await database.get_repository_candidate(bob["id"], "bob")
    assert stored["classification_status"] == "classifying"
    assert stored["classification"] is None
    assert await rows("SELECT id FROM collection_jobs") == ([{"id": existing_id}] if reuse else [])
    links = await rows("SELECT candidate_id FROM collection_job_candidates")
    assert len(links) == int(reuse)
    assert all(link["candidate_id"] != bob["id"] for link in links)


@pytest.mark.parametrize("accepted", [False, True])
async def test_rejected_or_already_collected_candidate_creates_no_job(database, accepted):
    await database.init_database()
    candidate = await candidate_for(database)
    if accepted:
        async with _require_database_pool().connection() as connection:
            await connection.execute(
                "INSERT INTO collected_datasets (dataset_url, title) VALUES (%s, 'Mortality')",
                (SOURCE_URL,),
            )
    result = await database.complete_candidate_classification(
        candidate["id"], "alice", decision(accepted)
    )
    assert result.candidate["classification_status"] == ("accepted" if accepted else "rejected")
    if accepted:
        assert result.collection.already_collected
        assert (await database.get_candidate_collection(candidate["id"], "alice")).already_collected
    else:
        assert result.collection is None
    assert await rows("SELECT id FROM collection_jobs") == []


async def test_atomic_completion_checks_owner_and_state(database):
    await database.init_database()
    candidate = await candidate_for(database)
    with pytest.raises(RuntimeError):
        await database.complete_candidate_classification(candidate["id"], "bob", decision())
    assert await rows("SELECT id FROM collection_jobs") == []
    await database.complete_candidate_classification(candidate["id"], "alice", decision())
    with pytest.raises(RuntimeError):
        await database.complete_candidate_classification(candidate["id"], "alice", decision())
    assert len(await rows("SELECT id FROM collection_jobs")) == 1
    assert await database.get_candidate_collection(candidate["id"], "bob") is None


@pytest.mark.parametrize("status", ["pending", "running", "done", "error"])
async def test_repeated_accepted_classification_only_reads_its_job(database, monkeypatch, status):
    await database.init_database()
    candidate = await candidate_for(database)
    result = await database.complete_candidate_classification(candidate["id"], "alice", decision())
    job_id = result.collection.job["id"]
    if status in {"running", "done"}:
        await database.mark_collection_job_running(job_id)
    if status == "done":
        await database.complete_collection_job(job_id, CollectionResult())
    if status == "error":
        await database.mark_collection_job_error(job_id, "test failure")

    def forbidden(*args, **kwargs):
        raise AssertionError("A repeated classification must not perform new work")

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", forbidden)
    monkeypatch.setattr(job_store, "_reserve_repository_candidate_collection_job", forbidden)
    for retry in (False, True):
        response = await classify_repository_result(
            candidate["id"], APIPrincipal("alice"), Response(), retry=retry
        )
        assert response.automatic_collection.job.id == job_id
        assert response.automatic_collection.job.status == status
    assert len(await rows("SELECT id FROM collection_jobs")) == 1
    assert len(await rows("SELECT * FROM collection_job_candidates")) == 1


async def test_followup_stays_on_associated_job_not_latest_url_job(database):
    await database.init_database()
    alice = await candidate_for(database)
    first = await database.complete_candidate_classification(alice["id"], "alice", decision())
    await database.mark_collection_job_error(first.collection.job["id"], "first attempt failed")
    bob = await candidate_for(database, "bob")
    second = await database.complete_candidate_classification(bob["id"], "bob", decision())
    assert first.collection.job["id"] != second.collection.job["id"]
    assert (await database.get_candidate_collection(alice["id"], "alice")).job[
        "id"
    ] == first.collection.job["id"]


async def test_legacy_acceptance_without_job_does_not_silently_start_work(database):
    await database.init_database()
    candidate = await candidate_for(database)
    async with _require_database_pool().connection() as connection:
        await _complete_candidate_classification(connection, candidate["id"], "alice", decision())
    response = await classify_repository_result(candidate["id"], APIPrincipal("alice"), Response())
    assert response.automatic_collection.error_code == "collection_not_scheduled"
    assert await rows("SELECT id FROM collection_jobs") == []


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
    from app.main import app, lifespan

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
    manager = collection_worker.collection_workers(concurrency=2, poll_interval=0.01)
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

    async def complete(job_id, result):
        if failure_stage == "finalize" and job_id == first["id"]:
            raise RuntimeError("test persistence failure")
        return await real_complete(job_id, result)

    monkeypatch.setattr(collection_worker, "collect_source_with_report", collect)
    monkeypatch.setattr(collection_worker, "complete_collection_job", complete)
    async with collection_worker.collection_workers(concurrency=1, poll_interval=0.01):

        async def done():
            return (await database.get_collection_job(second["id"]))["status"] == "done"

        await wait_until(done)
    failed = await database.get_collection_job(first["id"])
    assert failed["status"] == "error"
    assert "test " in failed["error"]
