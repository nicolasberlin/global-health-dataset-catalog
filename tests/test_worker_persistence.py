"""Real PostgreSQL commits with injected disconnects at finalization boundaries."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from unittest.mock import Mock

import pytest
from app import classification_worker, collection_worker, workers
from app.db import classification_votes as votes
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.search_progress import read_search_progress
from psycopg import OperationalError
from test_collection_workflow import candidate_for, decision, rows

from collector.storage.models import CollectedDataset, CollectionResult

pytestmark = pytest.mark.anyio


async def prepare(database, monkeypatch, kind, *, execution_error=False):
    await database.init_database()
    candidate = await candidate_for(database)
    candidate = await database.get_repository_candidate(candidate["id"], "alice")
    if kind == "collection":
        await database.complete_candidate_classification(candidate["id"], "alice", decision())
        item = await database.claim_pending_collection_job()
        module = collection_worker
        result = CollectionResult(datasets=[CollectedDataset(
            dataset_url=str(item["source_url"]), title="Mortality", description="",
            publisher="", hosting_platform="", uploader="", dataset_signals={},
        )])
        compute = Mock(return_value=result)
        monkeypatch.setattr(module, "collect_repository_candidate_with_report", compute)
        monkeypatch.setattr(module, "build_default_page_classifier", Mock())
        run = module._run_collection_job
        complete_name, fail_name = "complete_collection_job", "mark_collection_job_error"
    else:
        item = {**candidate, "owner_id": "alice"}
        module = classification_worker
        compute = Mock(return_value=decision())
        monkeypatch.setattr(module, "_classify", compute)
        run = module._run_classification
        complete_name = "complete_candidate_classification"
        fail_name = "fail_candidate_classification"
    if execution_error:
        compute.side_effect = RuntimeError("external work failed")
    monkeypatch.setattr(module, "persist_with_retry",
                        partial(workers.persist_with_retry, initial_delay=0))
    return module, item, run, compute, complete_name, fail_name


@pytest.mark.parametrize("kind", ["collection", "classification"])
@pytest.mark.parametrize("execution_error", [False, True])
@pytest.mark.parametrize("disconnect", ["before_commit", "after_commit"])
async def test_finalization_survives_disconnect_without_reexecuting(
    database, monkeypatch, kind, execution_error, disconnect,
):
    module, item, run, compute, complete_name, fail_name = await prepare(
        database, monkeypatch, kind, execution_error=execution_error,
    )
    operation_name = fail_name if execution_error else complete_name
    original = getattr(module, operation_name)
    calls = 0

    async def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if disconnect == "before_commit" and calls < 3:
            raise OperationalError("database unavailable")
        result = await original(*args, **kwargs)
        if disconnect == "after_commit" and calls == 1:
            raise OperationalError("commit acknowledgement lost")
        if disconnect == "after_commit":
            assert result is None  # Guarded repetition did not write again.
        return result

    monkeypatch.setattr(module, operation_name, interrupted)
    with ThreadPoolExecutor(1) as executor:
        await run(item, executor)
    compute.assert_called_once()
    assert calls == (3 if disconnect == "before_commit" else 2)
    if kind == "collection":
        stored = await database.get_collection_job(item["id"])
        assert stored["status"] == ("error" if execution_error else "done")
        assert stored["saved_count"] == int(not execution_error)
        assert len(await database.list_collected_datasets()) == int(not execution_error)
    else:
        stored = await database.get_repository_candidate(item["id"], "alice")
        assert stored["classification_status"] == ("error" if execution_error else "accepted")
        assert len(await rows("SELECT id FROM collection_jobs")) == int(not execution_error)
        links = await rows("SELECT * FROM collection_job_candidates")
        assert len(links) == int(not execution_error)


@pytest.mark.parametrize("kind", ["collection", "classification"])
async def test_lost_error_acknowledgement_cannot_overwrite_user_retry(database, monkeypatch, kind):
    module, item, run, compute, _, fail_name = await prepare(
        database, monkeypatch, kind, execution_error=True,
    )
    original = getattr(module, fail_name)
    retried = None
    calls = 0

    async def interrupted(*args, **kwargs):
        nonlocal calls, retried
        calls += 1
        result = await original(*args, **kwargs)
        if calls == 1:
            assert result is not None
            # Another consumer can claim the explicit retry while the first
            # consumer still believes its error write failed.
            if kind == "collection":
                await retry_collection_job_for_owner(item["id"], "alice")
                retried = await database.claim_pending_collection_job()
            else:
                await database.enqueue_candidate_classification(item["id"], "alice", retry=True)
                retried = await database.claim_candidate_classification()
            raise OperationalError("commit acknowledgement lost")
        assert result is None
        return result

    monkeypatch.setattr(module, fail_name, interrupted)
    with ThreadPoolExecutor(1) as executor:
        await run(item, executor)
    assert calls == 2
    compute.assert_called_once()
    assert retried["updated_at"] != item["updated_at"]
    if kind == "collection":
        stored = await database.get_collection_job(item["id"])
        assert stored["status"] == "running"
        assert await database.complete_collection_job(
            item["id"], CollectionResult(),
            expected_updated_at=datetime.fromisoformat(item["updated_at"]),
        ) is None
    else:
        stored = await database.get_repository_candidate(item["id"], "alice")
        assert stored["classification_status"] == "classifying"
        assert await database.complete_candidate_classification(
            item["id"], "alice", decision(),
            expected_updated_at=datetime.fromisoformat(item["updated_at"]),
        ) is None
    assert stored["updated_at"] == retried["updated_at"]
    assert stored["error"] == ""


async def test_guarded_classification_still_checks_owner(database, monkeypatch):
    _, item, _, _, _, _ = await prepare(database, monkeypatch, "classification")
    version = datetime.fromisoformat(item["updated_at"])
    assert await database.complete_candidate_classification(
        item["id"], "bob", decision(), expected_updated_at=version,
    ) is None
    assert await database.fail_candidate_classification(
        item["id"], "bob", "not allowed", expected_updated_at=version,
    ) is None
    stored = await database.get_repository_candidate(item["id"], "alice")
    assert stored["classification_status"] == "classifying"
    assert stored["updated_at"] == item["updated_at"]
    assert await rows("SELECT id FROM collection_jobs") == []


@pytest.mark.parametrize("kind", ["collection", "classification"])
@pytest.mark.parametrize("execution_error", [False, True])
async def test_concurrent_persistence_retries_finalize_one_claim(
    database, monkeypatch, kind, execution_error,
):
    module, item, _, compute, complete_name, fail_name = await prepare(
        database, monkeypatch, kind,
    )
    operation = getattr(module, fail_name if execution_error else complete_name)
    version = datetime.fromisoformat(item["updated_at"])
    outcome = "execution failed" if execution_error else compute.return_value
    args = (item["id"], outcome) if kind == "collection" else (item["id"], "alice", outcome)
    ready = asyncio.Event()
    recovering = 0

    async def retry():
        nonlocal recovering
        attempts = 0

        async def persist():
            nonlocal attempts, recovering
            attempts += 1
            if attempts == 1:
                raise OperationalError("database unavailable")
            recovering += 1
            if recovering == 2:
                ready.set()
            await ready.wait()
            return await operation(*args, expected_updated_at=version)

        return await workers.persist_with_retry(persist, initial_delay=0)

    results = await asyncio.wait_for(asyncio.gather(retry(), retry()), timeout=5)
    assert sum(result is not None for result in results) == 1
    if kind == "collection":
        stored = await database.get_collection_job(item["id"])
        assert stored["status"] == ("error" if execution_error else "done")
        assert len(await rows("SELECT id FROM dataset_discovery_observations")) == int(
            not execution_error
        )
        assert len(await database.list_collected_datasets()) == int(not execution_error)
    else:
        stored = await database.get_repository_candidate(item["id"], "alice")
        assert stored["classification_status"] == ("error" if execution_error else "accepted")
        assert len(await rows("SELECT id FROM collection_jobs")) == int(not execution_error)
        links = await rows("SELECT * FROM collection_job_candidates")
        assert len(links) == int(not execution_error)


@pytest.mark.parametrize("kind", ["collection", "classification"])
async def test_vote_progress_and_polling_preserve_completion_claim(database, monkeypatch, kind):
    _, item, run, compute, _, _ = await prepare(database, monkeypatch, kind)
    scope = {"job_id": item["id"]} if kind == "collection" else {"candidate_id": item["id"]}
    candidate_id = item["repository_candidate_id"] if kind == "collection" else item["id"]
    candidate = await database.get_repository_candidate(candidate_id, "alice")
    run_id = await votes.prepare_vote_run({"configuration": [{"voter_id": "a"}]}, **scope)
    vote = await votes.claim_vote(run_id, "a", **scope)
    await votes.finish_vote(
        run_id, "a", vote["attempt_token"], response={"accepted": True}, **scope,
    )
    await read_search_progress(candidate["search_session_id"], "alice")
    stored = (await database.get_collection_job(item["id"]) if kind == "collection"
              else await database.get_repository_candidate(item["id"], "alice"))
    assert stored["updated_at"] == item["updated_at"]
    assert stored["classification_progress"]["succeeded"] == 1
    with ThreadPoolExecutor(1) as executor:
        await run(item, executor)
    compute.assert_called_once()
    _, candidates, collections = await read_search_progress(candidate["search_session_id"], "alice")
    assert candidates[0]["classification_status"] == "accepted"
    expected_status = "done" if kind == "collection" else "pending"
    assert collections[candidate_id].job["status"] == expected_status
