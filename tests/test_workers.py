"""Persistence retries retain ownership without repeating external execution."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from unittest.mock import AsyncMock, Mock

import pytest
from app import classification_worker, collection_worker, workers
from psycopg import InterfaceError, OperationalError
from psycopg.errors import DeadlockDetected, DiskFull, SerializationFailure
from psycopg_pool import PoolTimeout

from collector.storage.models import CollectionResult

pytestmark = pytest.mark.anyio
VERSION = datetime(2026, 9, 25, tzinfo=timezone.utc)


@pytest.mark.parametrize("failure", [OperationalError, InterfaceError, PoolTimeout,
                                    SerializationFailure, DeadlockDetected])
async def test_transient_persistence_retries_until_success(failure):
    operation = AsyncMock(side_effect=[failure("outage"), failure("outage"), "saved"])
    assert await workers.persist_with_retry(operation, initial_delay=0) == "saved"
    assert operation.await_count == 3


@pytest.mark.parametrize("failure", [RuntimeError, ValueError, DiskFull])
async def test_permanent_errors_do_not_loop(failure):
    operation = AsyncMock(side_effect=failure("permanent"))
    with pytest.raises(failure):
        await workers.persist_with_retry(operation, initial_delay=0)
    assert operation.await_count == 1


async def test_persistence_backoff_is_capped(monkeypatch):
    pause = AsyncMock()
    monkeypatch.setattr(workers.asyncio, "sleep", pause)
    jitter = Mock(side_effect=lambda low, high: high)
    monkeypatch.setattr(workers.random, "uniform", jitter)
    operation = AsyncMock(side_effect=[OperationalError("offline")] * 7 + ["saved"])
    assert await workers.persist_with_retry(operation) == "saved"
    delays = [call.args[0] for call in pause.await_args_list]
    assert delays == [1, 2, 4, 8, 16, 30, 30]
    assert [call.args for call in jitter.call_args_list] == [(d / 2, d) for d in delays]


async def test_persistence_wait_is_cancellable():
    attempted = asyncio.Event()

    async def unavailable():
        attempted.set()
        raise OperationalError("offline")

    task = asyncio.create_task(workers.persist_with_retry(unavailable))
    await attempted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_consumer_keeps_slot_until_terminal_write_recovers(monkeypatch):
    stop, blocked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    claims = 0
    writes = 0

    async def claim():
        nonlocal claims
        claims += 1
        if claims == 1:
            return {"id": 1, "kind": "source", "source_url": "https://example.org",
                    "updated_at": VERSION.isoformat()}
        stop.set()
        return None

    async def complete(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OperationalError("offline")
        blocked.set()
        await release.wait()

    compute = Mock(return_value=CollectionResult())
    monkeypatch.setattr(collection_worker, "collect_source_with_report", compute)
    monkeypatch.setattr(collection_worker, "build_default_page_classifier", Mock())
    monkeypatch.setattr(collection_worker, "PostgresVoteStore", Mock())
    monkeypatch.setattr(collection_worker, "complete_collection_job", complete)
    monkeypatch.setattr(collection_worker, "persist_with_retry",
                        partial(workers.persist_with_retry, initial_delay=0))
    with ThreadPoolExecutor(1) as executor:
        task = asyncio.create_task(workers._consume(
            stop, executor, .001, claim, collection_worker._run_collection_job,
        ))
        try:
            await asyncio.wait_for(blocked.wait(), 2)
            assert claims == 1
            release.set()
            await asyncio.wait_for(task, 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    compute.assert_called_once()
    assert writes == 2
    assert claims == 2


@pytest.mark.parametrize("kind", ["collection", "classification"])
@pytest.mark.parametrize("stage", ["success", "execution_error", "permanent_finalization_error"])
async def test_workers_retry_only_persistence(monkeypatch, kind, stage):
    module = collection_worker if kind == "collection" else classification_worker
    monkeypatch.setattr(module, "persist_with_retry",
                        partial(workers.persist_with_retry, initial_delay=0))
    monkeypatch.setattr(module, "PostgresVoteStore", Mock())
    compute = Mock(return_value=CollectionResult() if kind == "collection" else object())
    if stage == "execution_error":
        compute.side_effect = RuntimeError("execution failed")
    complete = AsyncMock(side_effect=(
        [OperationalError("offline"), None] if stage == "success"
        else RuntimeError("invalid result")
    ))
    fail = AsyncMock(side_effect=[PoolTimeout("offline"), OperationalError("offline"), None])
    if kind == "collection":
        monkeypatch.setattr(module, "build_default_page_classifier", Mock())
        monkeypatch.setattr(module, "collect_source_with_report", compute)
        monkeypatch.setattr(module, "complete_collection_job", complete)
        monkeypatch.setattr(module, "mark_collection_job_error", fail)
        item = {"id": 1, "kind": "source", "source_url": "https://example.org",
                "updated_at": VERSION.isoformat()}
        run = module._run_collection_job
    else:
        monkeypatch.setattr(module, "_classify", compute)
        monkeypatch.setattr(module, "complete_candidate_classification", complete)
        monkeypatch.setattr(module, "fail_candidate_classification", fail)
        item = {"id": "candidate", "owner_id": "alice", "updated_at": VERSION.isoformat()}
        run = module._run_classification
    with ThreadPoolExecutor(1) as executor:
        await run(item, executor)
    compute.assert_called_once()
    assert complete.await_count == (2 if stage == "success" else int(stage != "execution_error"))
    assert fail.await_count == (0 if stage == "success" else 3)
    for call in complete.await_args_list + fail.await_args_list:
        assert call.kwargs["expected_updated_at"] == VERSION
