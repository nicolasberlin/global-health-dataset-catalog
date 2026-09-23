"""Bridge classifier threads to the backend event loop's PostgreSQL pool."""

from __future__ import annotations

import asyncio

from app.db.classification_votes import claim_vote, finish_vote, prepare_vote_run


class PostgresVoteStore:
    def __init__(self, loop, *, candidate_id=None, job_id=None):
        self.loop = loop
        self.scope = {"candidate_id": candidate_id, "job_id": job_id}

    def _wait(self, operation):
        return asyncio.run_coroutine_threadsafe(operation, self.loop).result()

    def run(self, snapshot, voter_id, invoke):
        run_id = self._wait(prepare_vote_run(snapshot, **self.scope))
        vote = self._wait(claim_vote(run_id, voter_id, **self.scope))
        if vote["status"] == "succeeded":
            return vote["response"]
        try:
            response = invoke()
        except Exception as exception:
            self._wait(
                finish_vote(
                    run_id,
                    voter_id,
                    vote["attempt_token"],
                    error=str(exception) or type(exception).__name__,
                    **self.scope,
                )
            )
            raise
        self._wait(
            finish_vote(
                run_id,
                voter_id,
                vote["attempt_token"],
                response=response,
                **self.scope,
            )
        )
        return response
