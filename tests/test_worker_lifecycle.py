"""Regression checks for retained outcomes, bounded shutdown and thread fencing."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.workers import runtime as workers
from app.workers import sql_retries
from app.workers import stores as vote_module
from app.workers.classification import workers as classification_worker
from app.workers.collection import workers as collection_worker
from app.workers.search import workers as search_worker
from app.workers.sql_retries import persist_with_retry
from app.workers.state import request_worker_stop, workers_ready
from app.workers.stores import PostgresVoteStore
from helpers.workers import StubWorker, execute_worker
from psycopg import OperationalError
from psycopg.errors import DiskFull, QueryCanceled

from collector import observability
from collector.diagnostics import PersistenceFailure
from collector.execution import ExecutionControl, ExecutionStopped, execution_control
from collector.storage.models import CollectionResult

pytestmark = pytest.mark.anyio
VERSION = datetime(2026, 10, 14, tzinfo=timezone.utc).isoformat()


def install_execution(monkeypatch, kind):
    item = {"id": 1, "kind": "source", "source_url": "https://example.org",
            "updated_at": VERSION, "owner_id": "alice", "query": "sensitive-query",
            "client_key": None}
    if kind == "collection":
        module = collection_worker
        compute = Mock(return_value=CollectionResult())
        monkeypatch.setattr(module, "build_default_page_classifier", Mock())
        monkeypatch.setattr(module, "collect_source_with_report", compute)
        run = partial(execute_worker, module)
        complete_name, fail_name = "complete_collection_job", "mark_collection_job_error"
    elif kind == "classification":
        module = classification_worker
        item["id"] = uuid4()
        compute = Mock(return_value=object())
        monkeypatch.setattr(module, "_classify", compute)
        run = partial(execute_worker, module)
        complete_name = "complete_candidate_classification"
        fail_name = "fail_candidate_classification"
    else:
        module = search_worker
        item["id"] = uuid4()
        compute = AsyncMock(return_value=[object()])
        monkeypatch.setattr(module, "lookup_local", compute)
        run = partial(execute_worker, module)
        complete_name, fail_name = "complete_discovery", "fail_discovery"
    monkeypatch.setattr(module, "persist_with_retry", partial(persist_with_retry, initial_delay=0))
    return module, item, compute, run, complete_name, fail_name


@pytest.mark.parametrize("kind", ["collection", "classification", "search"])
@pytest.mark.parametrize("failure", [DiskFull, QueryCanceled])
async def test_storage_repair_saves_original_outcome_without_reexecuting(
    monkeypatch, kind, failure,
):
    module, item, compute, run, complete_name, fail_name = install_execution(monkeypatch, kind)
    complete = AsyncMock(side_effect=[failure("simulated failure"), failure("failure"), None])
    fail = AsyncMock()
    monkeypatch.setattr(module, complete_name, complete)
    monkeypatch.setattr(module, fail_name, fail)
    with ThreadPoolExecutor(1) as executor:
        await asyncio.wait_for(run(item, executor), 2)
    assert compute.call_count == 1
    assert complete.await_count == 3
    assert all(call.args[1] is complete.await_args_list[0].args[1]
               for call in complete.await_args_list)
    fail.assert_not_awaited()


async def test_unexpected_vote_save_failure_retains_response_and_invokes_once(monkeypatch):
    run_id, attempt_token = uuid4(), uuid4()
    monkeypatch.setattr(vote_module, "prepare_vote_run", AsyncMock(return_value=run_id))
    monkeypatch.setattr(vote_module, "claim_vote", AsyncMock(return_value={
        "status": "running", "attempt_token": attempt_token, "cycle_attempts": 1,
    }))
    finish = AsyncMock(side_effect=[RuntimeError("schema unavailable"), DiskFull("full"), None])
    monkeypatch.setattr(vote_module, "finish_vote", finish)
    monkeypatch.setattr(vote_module, "persist_with_retry",
                        partial(persist_with_retry, initial_delay=0))
    response = {"accepted": False}
    invoke = Mock(return_value=response)
    store = PostgresVoteStore(asyncio.get_running_loop(), candidate_id=uuid4())
    with ThreadPoolExecutor(1) as executor:
        result = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
            executor, store.run, {"configuration": [{"voter_id": "a"}]}, "a", invoke,
        ), 2)
    assert result is response
    invoke.assert_called_once()
    assert finish.await_count == 3
    assert all(call.kwargs["response"] is response for call in finish.await_args_list)


async def test_superseded_vote_is_not_retried_as_persistence_failure(monkeypatch):
    operation = AsyncMock(side_effect=PersistenceFailure("Claim superseded."))
    with pytest.raises(PersistenceFailure):
        await persist_with_retry(operation, initial_delay=0, retry_unexpected=True)
    operation.assert_awaited_once()


async def test_stopped_vote_bridge_does_not_submit_or_invoke(monkeypatch):
    submit = Mock()
    monkeypatch.setattr(vote_module.asyncio, "run_coroutine_threadsafe", submit)
    control = ExecutionControl()
    control.abort()
    token = execution_control.set(control)
    invoke = Mock()
    try:
        with pytest.raises(ExecutionStopped):
            PostgresVoteStore(asyncio.get_running_loop()).run({}, "a", invoke)
    finally:
        execution_control.reset(token)
    submit.assert_not_called()
    invoke.assert_not_called()


@pytest.mark.parametrize("kind", ["collection", "classification", "search"])
async def test_failed_terminal_write_retains_slot_and_recovers_health(monkeypatch, kind):
    module, item, compute, run, complete_name, fail_name = install_execution(monkeypatch, kind)
    monkeypatch.setattr(module, complete_name, AsyncMock(side_effect=ValueError("invalid outcome")))
    first_failure, repaired, saved = asyncio.Event(), asyncio.Event(), asyncio.Event()
    claims = 0

    async def claim(*, claim_token):
        nonlocal claims
        claims += 1
        return item

    async def fail(*args, **kwargs):
        if not repaired.is_set():
            first_failure.set()
            raise DiskFull("simulated repairable failure")
        saved.set()
        request_worker_stop()

    monkeypatch.setattr(module, fail_name, fail)
    manager = workers.persisted_workers(
        StubWorker(claim=claim, execute=run, name=kind), concurrency=1, shutdown_timeout=0.1
    )
    await manager.__aenter__()
    try:
        await asyncio.wait_for(first_failure.wait(), 2)
        assert not workers_ready()
        assert claims == 1 and compute.call_count == 1
        repaired.set()
        await asyncio.wait_for(saved.wait(), 2)
        await asyncio.sleep(0)
        assert workers_ready()
    finally:
        repaired.set()
        await manager.__aexit__(None, None, None)
    assert claims == 1 and compute.call_count == 1


async def test_stop_interrupts_acquisition_backoff(monkeypatch):
    attempted = asyncio.Event()
    claims = 0

    async def claim(*, claim_token):
        nonlocal claims
        claims += 1
        attempted.set()
        raise OperationalError("simulated unavailable database")

    monkeypatch.setattr(workers, "persist_with_retry",
                        partial(sql_retries.persist_with_retry, initial_delay=30))
    manager = workers.persisted_workers(
        StubWorker(claim=claim, execute=AsyncMock(), name="search"),
        concurrency=1,
        shutdown_timeout=0.5,
    )
    await manager.__aenter__()
    await attempted.wait()
    await asyncio.wait_for(manager.__aexit__(None, None, None), .2)
    assert claims == 1


async def test_expired_shutdown_cancels_bridge_without_late_write():
    entered, cancelled, thread_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()

    async def pending_write():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    def bridge():
        try:
            PostgresVoteStore(loop)._wait(pending_write)
        except ExecutionStopped:
            pass
        finally:
            loop.call_soon_threadsafe(thread_finished.set)

    async def execute(item, executor):
        from contextvars import copy_context
        await loop.run_in_executor(executor, copy_context().run, bridge)

    manager = workers.persisted_workers(
        StubWorker(claim=AsyncMock(return_value={"id": 1}), execute=execute, name="classification"),
        concurrency=1,
        shutdown_timeout=0.03,
    )
    await manager.__aenter__()
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(manager.__aexit__(None, None, None), .5)
    await asyncio.wait_for(cancelled.wait(), .5)
    await asyncio.wait_for(thread_finished.wait(), .5)


async def test_inflight_collection_cannot_finalize_after_forced_shutdown(monkeypatch):
    module, item, _, run, complete_name, _ = install_execution(monkeypatch, "collection")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    complete = AsyncMock()

    def collect(*args, **kwargs):
        entered.set()
        release.wait()
        finished.set()
        return CollectionResult()

    monkeypatch.setattr(module, "collect_source_with_report", collect)
    monkeypatch.setattr(module, complete_name, complete)
    manager = workers.persisted_workers(
        StubWorker(claim=AsyncMock(return_value=item), execute=run, name="collection"),
        concurrency=1,
        shutdown_timeout=0.03,
    )
    await manager.__aenter__()
    try:
        while not entered.is_set():
            await asyncio.sleep(.001)
        await asyncio.wait_for(manager.__aexit__(None, None, None), .5)
    finally:
        release.set()
    while not finished.is_set():
        await asyncio.sleep(.001)
    complete.assert_not_awaited()


async def test_shared_shutdown_budget_starts_on_stop_and_is_not_multiplied():
    from app.workers.state import shutdown_budget

    entered = asyncio.Event()

    async def execute(item, executor):
        entered.set()
        await asyncio.Event().wait()

    managers = []
    async with workers.worker_shutdown_budget(seconds=.03):
        assert shutdown_budget.get().deadline is None
        for queue in ("collection", "classification", "search"):
            manager = workers.persisted_workers(
                StubWorker(claim=AsyncMock(return_value={"id": 1}), execute=execute, name=queue),
                concurrency=1,
            )
            await manager.__aenter__()
            managers.append(manager)
        await entered.wait()
        assert shutdown_budget.get().deadline is None
        request_worker_stop()
        assert shutdown_budget.get().deadline is not None

        async def close():
            for manager in reversed(managers):
                await manager.__aexit__(None, None, None)

        await asyncio.wait_for(close(), .08)


async def test_daemon_executor_does_not_join_blocked_call_at_process_exit():
    source = """
import threading
from collector.execution import BoundedThreadExecutor
started = threading.Event()
def blocked():
    started.set()
    threading.Event().wait()
executor = BoundedThreadExecutor(1)
executor.submit(blocked)
assert started.wait(1)
executor.shutdown(wait=False, cancel_futures=True)
"""
    completed = subprocess.run([sys.executable, "-c", source], timeout=2, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode()


async def test_search_logs_have_correlation_without_query(monkeypatch, caplog):
    module, item, _, run, complete_name, _ = install_execution(monkeypatch, "search")
    monkeypatch.setattr(module, complete_name, AsyncMock())
    monkeypatch.setattr(observability.logger, "propagate", True)
    caplog.set_level(logging.INFO, logger="collector.operations")
    with ThreadPoolExecutor(1) as executor:
        await run(item, executor)
    records = [json.loads(record.message) for record in caplog.records
               if record.name == "collector.operations"]
    assert records and all(record["search_id"] == str(item["id"]) for record in records)
    assert "sensitive-query" not in caplog.text


async def test_superseded_search_skips_provider_and_finalization(monkeypatch, caplog):
    module, item, lookup, run, complete_name, fail_name = install_execution(monkeypatch, "search")
    lookup.return_value = []
    reserve = AsyncMock(return_value=False)
    provider = Mock()
    complete, fail = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module, "reserve_external_search", reserve)
    monkeypatch.setattr(module, "search_repository_metadata", provider)
    monkeypatch.setattr(module, complete_name, complete)
    monkeypatch.setattr(module, fail_name, fail)
    # Pytest also attaches to non-propagating loggers after application startup.
    # Capture directly rather than enabling a second path through the root logger.
    monkeypatch.setattr(observability.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(observability.logger, "propagate", False)
    caplog.set_level(logging.INFO, logger="collector.operations")

    with ThreadPoolExecutor(1) as executor:
        await run(item, executor)

    reserve.assert_awaited_once_with(item)
    provider.assert_not_called()
    complete.assert_not_awaited()
    fail.assert_not_awaited()
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "collector.operations"
    ]
    finished = [record for record in records if record["event"] == "search_finished"]
    assert len(finished) == 1
    assert finished[0]["search_id"] == str(item["id"])
    assert finished[0]["outcome"] == "superseded"
