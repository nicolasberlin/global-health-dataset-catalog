"""Thread bridge lifecycle and stage-specific persistence failures."""

from __future__ import annotations

import asyncio
import inspect
import threading
from datetime import datetime, timezone
from functools import partial
from unittest.mock import AsyncMock

import pytest
from app.workers import stores
from psycopg.errors import InsufficientPrivilege

from collector.classification.page import PageClassificationError
from collector.diagnostics import PersistenceFailure, exception_diagnostics
from collector.execution import ExecutionControl, ExecutionStopped, execution_control

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("failure", ["superseded", "database"])
async def test_collection_trace_failure_keeps_collection_stage(monkeypatch, failure):
    write = (
        AsyncMock(return_value=False)
        if failure == "superseded"
        else AsyncMock(side_effect=InsufficientPrivilege("Trace insert denied."))
    )
    monkeypatch.setattr(stores, "write_collection_trace", write)
    version = datetime(2026, 10, 30, tzinfo=timezone.utc)
    trace = stores.PostgresCollectionTraceWriter(asyncio.get_running_loop(), 1, version)
    observation = {"method": "direct", "status": "running"}

    with pytest.raises(PersistenceFailure) as caught:
        await asyncio.to_thread(trace, 0, observation)

    write.assert_awaited_once_with(1, version, 0, observation)
    (diagnostic,) = exception_diagnostics(caught.value, "collection")
    assert diagnostic.code == "persistence_failed"
    assert diagnostic.stage == "collection"


async def test_vote_bridge_runs_sql_on_loop_and_returns_its_result():
    loop = asyncio.get_running_loop()
    store = stores.PostgresVoteStore(loop)
    response = {"accepted": False}
    executed_on = []

    async def operation():
        assert asyncio.get_running_loop() is loop
        executed_on.append(threading.get_ident())
        return response

    assert await asyncio.to_thread(store._wait, operation) is response
    assert executed_on == [threading.get_ident()]


@pytest.mark.parametrize("kind", ["vote", "trace"])
async def test_submission_failure_closes_coroutine_and_keeps_stage(monkeypatch, kind):
    submitted = []
    failure = RuntimeError("Loop closed during submission.")

    def reject(coroutine, loop):
        submitted.append(coroutine)
        raise failure

    monkeypatch.setattr(stores.asyncio, "run_coroutine_threadsafe", reject)
    loop = asyncio.get_running_loop()
    if kind == "vote":
        call = partial(stores.PostgresVoteStore(loop)._wait, AsyncMock())
        stage = "classification"
    else:
        trace = stores.PostgresCollectionTraceWriter(loop, 1, datetime.now(timezone.utc))
        call = partial(trace, 0, {})
        stage = "collection"

    with pytest.raises(PersistenceFailure) as caught:
        await asyncio.to_thread(call)

    assert len(submitted) == 1
    assert inspect.getcoroutinestate(submitted[0]) == inspect.CORO_CLOSED
    assert caught.value.__cause__ is failure
    assert caught.value.diagnostics[0].stage == stage


async def test_submission_abort_closes_coroutine_and_propagates_cancellation(monkeypatch):
    submitted = []

    def abort(coroutine, loop):
        submitted.append(coroutine)
        raise ExecutionStopped()

    monkeypatch.setattr(stores.asyncio, "run_coroutine_threadsafe", abort)
    store = stores.PostgresVoteStore(asyncio.get_running_loop())
    with pytest.raises(ExecutionStopped):
        await asyncio.to_thread(store._wait, AsyncMock())

    assert len(submitted) == 1
    assert inspect.getcoroutinestate(submitted[0]) == inspect.CORO_CLOSED


@pytest.mark.parametrize(
    "failure",
    [
        PageClassificationError("Not due."),
        PersistenceFailure("Old."),
    ],
)
async def test_vote_bridge_preserves_domain_failure(failure):
    store = stores.PostgresVoteStore(asyncio.get_running_loop())
    operation = AsyncMock(side_effect=failure)

    with pytest.raises(type(failure)) as caught:
        await asyncio.to_thread(store._wait, operation)

    assert caught.value is failure
    operation.assert_awaited_once()


async def test_stopping_execution_cancels_submitted_bridge():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    control = ExecutionControl()
    store = stores.PostgresVoteStore(asyncio.get_running_loop())

    async def pending_write():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    token = execution_control.set(control)
    task = asyncio.create_task(asyncio.to_thread(store._wait, pending_write))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        control.abort()
        with pytest.raises(ExecutionStopped):
            await asyncio.wait_for(task, 1)
        await asyncio.wait_for(cancelled.wait(), 1)
    finally:
        control.abort()
        await asyncio.gather(task, return_exceptions=True)
        execution_control.reset(token)
