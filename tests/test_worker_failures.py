"""Failure policy preserves outcomes across persistence, cancellation and overlap."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import partial
from unittest.mock import AsyncMock

import pytest
from app.workers.failures import FailureHandler
from app.workers.sql_retries import persist_with_retry
from psycopg import OperationalError

from collector.diagnostics import Diagnostic, PipelineFailure

pytestmark = pytest.mark.anyio


def handler(*, retry, fail, stage="classification"):
    return FailureHandler(
        stage=stage,
        retry=retry,
        fail=fail,
        persist=partial(persist_with_retry, initial_delay=0),
    )


@pytest.mark.parametrize("stage", ["classification", "collection"])
async def test_saving_failure_never_schedules_model_retry_even_with_model_diagnostics(stage):
    job = {"id": 1}
    failure = PipelineFailure(
        "Could not publish the computed outcome.",
        diagnostics=[Diagnostic("llm_timeout", "classification", voter_id="model-a")],
    )
    retry, fail = AsyncMock(), AsyncMock()

    await handler(retry=retry, fail=fail, stage=stage).handle(job, failure, saving=True)

    retry.assert_not_awaited()
    fail.assert_awaited_once_with(job, str(failure), [Diagnostic("persistence_failed", stage)])


async def test_terminal_persistence_retries_keep_original_error_and_diagnostics():
    job = {"id": 1}
    original = Diagnostic("llm_configuration_error", "classification", voter_id="model-a")
    failure = PipelineFailure("Model configuration is unavailable.", diagnostics=[original])
    attempts = []

    async def fail(item, error, diagnostics):
        attempts.append((item, error, diagnostics))
        if len(attempts) == 1:
            raise RuntimeError("Unexpected terminal write failure.")
        if len(attempts) == 2:
            raise OperationalError("Transient terminal write failure.")

    retry = AsyncMock()
    await asyncio.wait_for(handler(retry=retry, fail=fail).handle(job, failure, saving=False), 1)

    retry.assert_not_awaited()
    assert len(attempts) == 3
    for item, error, diagnostics in attempts:
        assert item is job
        assert error == str(failure)
        assert diagnostics is failure.diagnostics
        assert diagnostics == [original]


async def test_cancellation_during_retry_scheduling_propagates_without_terminal_write():
    entered = asyncio.Event()
    scheduling_cancelled = asyncio.Event()

    async def retry(job, diagnostics):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            scheduling_cancelled.set()

    fail = AsyncMock()
    failure = PipelineFailure(
        "Model timed out.",
        diagnostics=[Diagnostic("llm_timeout", "classification")],
    )
    task = asyncio.create_task(
        handler(retry=retry, fail=fail).handle(
            {"id": 1},
            failure,
            saving=False,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert scheduling_cancelled.is_set()
    fail.assert_not_awaited()


async def test_shared_handler_keeps_enriched_diagnostics_for_each_refused_retry():
    entered, release = asyncio.Event(), asyncio.Event()
    jobs = [{"id": 1}, {"id": 2}]
    failures = {
        job["id"]: PipelineFailure(
            f"Model {job['id']} timed out.",
            diagnostics=[Diagnostic("llm_timeout", "classification", voter_id=str(job["id"]))],
        )
        for job in jobs
    }
    enriched = {}
    saved = {}

    async def retry(job, diagnostics):
        assert diagnostics is failures[job["id"]].diagnostics
        enriched[job["id"]] = [
            replace(diagnostics[0], attempt=job["id"], max_attempts=3, recovery="manual"),
            Diagnostic("collection_budget_exhausted", "collection"),
        ]
        if len(enriched) == 2:
            entered.set()
        await release.wait()
        return False, enriched[job["id"]]

    async def fail(job, error, diagnostics):
        saved[job["id"]] = (error, diagnostics)

    shared = handler(retry=retry, fail=fail, stage="collection")
    tasks = [
        asyncio.create_task(shared.handle(job, failures[job["id"]], saving=False)) for job in jobs
    ]
    try:
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        release.set()
        await asyncio.gather(*tasks)

    assert len(saved) == 2
    for job in jobs:
        error, diagnostics = saved[job["id"]]
        assert error == str(failures[job["id"]])
        assert diagnostics is enriched[job["id"]]
        assert diagnostics[0].voter_id == str(job["id"])
        assert diagnostics[1].code == "collection_budget_exhausted"


async def test_unexpected_scheduler_error_propagates_without_reclassifying_original_failure():
    failure = PipelineFailure(
        "Model timed out.",
        diagnostics=[Diagnostic("llm_timeout", "classification")],
    )
    scheduler_error = ValueError("Unexpected scheduler invariant violation.")
    retry, fail = AsyncMock(side_effect=scheduler_error), AsyncMock()

    with pytest.raises(ValueError) as caught:
        await handler(retry=retry, fail=fail).handle({"id": 1}, failure, saving=False)

    assert caught.value is scheduler_error
    retry.assert_awaited_once()
    fail.assert_not_awaited()
