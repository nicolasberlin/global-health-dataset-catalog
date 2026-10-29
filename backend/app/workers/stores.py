"""Bridge worker threads to the event loop for durable votes and collection traces."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.db.classification.votes import claim_vote, finish_vote, prepare_vote_run
from app.db.collection.traces import write_collection_trace
from app.workers.sql_retries import persist_with_retry
from collector.classification.page import PageClassificationError
from collector.diagnostics import PersistenceFailure, PipelineFailure, voter_diagnostics
from collector.execution import check_execution_active, wait_for_future


class PostgresVoteStore:
    def __init__(self, loop, *, candidate_id=None, job_id=None, expected_updated_at=None):
        self.loop = loop
        self.scope = {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "expected_updated_at": expected_updated_at,
        }

    def _wait(self, operation, *, finalizing=False):
        check_execution_active()
        coroutine = persist_with_retry(
            operation, retry_storage_failures=True, retry_unexpected=finalizing,
        )
        try:
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except BaseException:
                coroutine.close()
                raise
            return wait_for_future(future)
        except (PageClassificationError, PersistenceFailure):
            raise
        except Exception as exception:
            raise PersistenceFailure("Vote persistence failed.") from exception

    def run(self, snapshot, voter_id, invoke):
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
                ), finalizing=True,
            )
            raise
        self._wait(
            lambda: finish_vote(
                run_id,
                voter_id,
                vote["attempt_token"],
                response=response,
                **self.scope,
            ), finalizing=True,
        )
        return response


class PostgresCollectionTrace:
    def __init__(self, loop, job_id, version):
        self.loop, self.job_id, self.version = loop, job_id, version

    def __call__(self, sequence, observation):
        check_execution_active()
        coroutine = persist_with_retry(
            lambda: write_collection_trace(self.job_id, self.version, sequence, observation),
            retry_storage_failures=True,
        )
        try:
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except BaseException:
                coroutine.close()
                raise
            accepted = wait_for_future(future)
            if not accepted:
                raise PersistenceFailure("Collection claim is no longer current.")
        except PersistenceFailure:
            raise
        except Exception as exc:
            raise PersistenceFailure("Collection trace could not be saved.") from exc
