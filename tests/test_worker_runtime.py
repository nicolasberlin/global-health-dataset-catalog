"""The object contract retains failed attempts until recovery is acknowledged."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from unittest.mock import AsyncMock

import pytest
from app.db.execution.application_lock import ApplicationLockLost
from app.workers import runtime
from app.workers.sql_retries import persist_with_retry
from helpers.workers import StubWorker
from psycopg import OperationalError

pytestmark = pytest.mark.anyio


async def test_consumer_retries_recovery_before_acquiring_another_job(monkeypatch):
    stop, recovering, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    job = {"id": 1}
    claims, recoveries = [], []

    async def claim(*, claim_token):
        claims.append(claim_token)
        if len(claims) == 1:
            return job
        stop.set()
        return None

    async def recover(item):
        recoveries.append(item)
        if len(recoveries) == 1:
            raise OperationalError("Recovery acknowledgement is temporarily unavailable")
        recovering.set()
        await release.wait()

    worker = StubWorker(
        name="collection",
        claim=claim,
        execute=AsyncMock(side_effect=ValueError("Unexpected execution failure")),
        recover=recover,
    )
    monkeypatch.setattr(runtime, "persist_with_retry", partial(persist_with_retry, initial_delay=0))
    with ThreadPoolExecutor(1) as executor:
        task = asyncio.create_task(runtime._consume(stop, executor, 0.001, worker))
        try:
            await asyncio.wait_for(recovering.wait(), 1)
            assert len(claims) == 1
            worker.execute.assert_awaited_once_with(job, executor)
            release.set()
            await asyncio.wait_for(task, 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert len(claims) == 2 and claims[0] != claims[1]
    assert len(recoveries) == 2 and all(item is job for item in recoveries)


async def test_ownership_loss_during_recovery_does_not_reacquire_or_retry():
    job = {"id": 1}
    worker = StubWorker(
        claim=AsyncMock(return_value=job),
        execute=AsyncMock(side_effect=ValueError("Unexpected execution failure")),
        recover=AsyncMock(side_effect=ApplicationLockLost("Ownership lost")),
    )
    with ThreadPoolExecutor(1) as executor:
        with pytest.raises(ApplicationLockLost):
            await runtime._consume(asyncio.Event(), executor, 0.001, worker)

    worker.claim.assert_awaited_once()
    worker.recover.assert_awaited_once_with(job)
