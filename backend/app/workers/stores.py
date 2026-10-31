"""Bridge worker threads to the event loop for durable votes and collection traces."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID, uuid4

from app.db.classification.votes import claim_vote, finish_vote, prepare_vote_run
from app.db.collection.traces import write_collection_trace
from app.workers.sql_retries import persist_with_retry
from collector.classification.page import PageClassificationError
from collector.diagnostics import PersistenceFailure, PipelineFailure, voter_diagnostics
from collector.execution import check_execution_active, wait_for_future

T = TypeVar("T")


def _submit_and_wait(
    loop: asyncio.AbstractEventLoop,
    coroutine: Coroutine[Any, Any, T],
) -> T:
    """Submit from a worker thread to its active loop and wait with cancellation.

    Callers check execution before creating the coroutine. Closing it when
    submission fails avoids leaving an unawaited coroutine behind.
    """
    try:
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    except BaseException:
        coroutine.close()
        raise
    return wait_for_future(future)


class PostgresVoteStore:
    """Checkpoint validated votes while keeping model calls outside SQL retries.

    Synchronous methods run in worker threads, never on ``loop``'s own thread.
    ``expected_updated_at`` fences writes to the parent task's claimed version.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        candidate_id: UUID | None = None,
        job_id: int | None = None,
        expected_updated_at: datetime | None = None,
    ) -> None:
        self.loop = loop
        self.scope = {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "expected_updated_at": expected_updated_at,
        }

    def _wait(self, operation: Callable[[], Awaitable[T]], *, finalizing: bool = False) -> T:
        """Wait for SQL; finalization retains an outcome through unexpected write errors."""
        check_execution_active()
        coroutine = persist_with_retry(
            operation,
            retry_storage_failures=True,
            retry_unexpected=finalizing,
        )
        try:
            return _submit_and_wait(self.loop, coroutine)
        except (PageClassificationError, PersistenceFailure):
            raise
        except Exception as exception:
            raise PersistenceFailure("Vote persistence failed.") from exception

    def run(
        self,
        snapshot: dict[str, object],
        voter_id: str,
        invoke: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        """Reuse successful votes, including negative decisions, or invoke once.

        A stable token makes claim retries safe after a lost acknowledgement.
        Both results and provider failures are saved before returning or raising.
        """
        run_id = self._wait(lambda: prepare_vote_run(snapshot, **self.scope))
        token = uuid4()
        vote = self._wait(lambda: claim_vote(run_id, voter_id, token=token, **self.scope))
        if vote["status"] == "succeeded":
            return vote["response"]
        try:
            check_execution_active()
            response = invoke()
        except Exception as exception:
            diagnostics = voter_diagnostics(exception, voter_id, vote["cycle_attempts"])
            if isinstance(exception, PipelineFailure):
                exception.diagnostics = diagnostics
            error = str(exception) or type(exception).__name__
            self._wait(
                lambda: finish_vote(
                    run_id,
                    voter_id,
                    vote["attempt_token"],
                    error=error,
                    errors=[item.to_dict() for item in diagnostics],
                    **self.scope,
                ),
                finalizing=True,
            )
            raise
        self._wait(
            lambda: finish_vote(
                run_id,
                voter_id,
                vote["attempt_token"],
                response=response,
                **self.scope,
            ),
            finalizing=True,
        )
        return response


class PostgresCollectionTraceWriter:
    """Save collection observations from a worker thread under its claim version."""

    def __init__(self, loop: asyncio.AbstractEventLoop, job_id: int, version: datetime) -> None:
        self.loop, self.job_id, self.version = loop, job_id, version

    def __call__(self, sequence: int, observation: dict[str, object]) -> None:
        """Persist an observation; a superseded claim must stop further collection work."""
        check_execution_active()
        coroutine = persist_with_retry(
            lambda: write_collection_trace(self.job_id, self.version, sequence, observation),
            retry_storage_failures=True,
        )
        try:
            accepted = _submit_and_wait(self.loop, coroutine)
            if not accepted:
                raise PersistenceFailure(
                    "Collection claim is no longer current.",
                    stage="collection",
                )
        except PersistenceFailure:
            raise
        except Exception as exc:
            raise PersistenceFailure(
                "Collection trace could not be saved.",
                stage="collection",
            ) from exc
