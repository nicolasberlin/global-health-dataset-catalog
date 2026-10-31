"""Claim and finalize individual votes for candidate and collection classifications."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.db.classification.voting.state import _lock_run, _publish_progress, _scope
from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.serialization import _jsonb
from app.policies.retries import TRANSIENT, RetryPolicy, as_datetime
from collector.classification.page import PageClassificationError
from collector.diagnostics import Diagnostic, PersistenceFailure


async def claim_vote(
    run_id, voter_id, *, candidate_id=None, job_id=None, expected_updated_at=None, token=None
):
    """Claim under the parent version; replaying the same token recovers the current vote."""
    token = token or uuid4()
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            scope = await _scope(connection, candidate_id, job_id, expected_updated_at)
            await _lock_run(connection, run_id)
            vote = await _fetchone(
                connection,
                "SELECT * FROM classification_votes WHERE run_id = %s AND voter_id = %s",
                (run_id, voter_id),
            )
            if vote is None:
                raise PersistenceFailure("Model vote is missing.")
            if vote["status"] == "succeeded":
                return vote
            if vote["status"] == "running":
                if vote["attempt_token"] == token:
                    return vote  # Lost claim acknowledgement, not another invocation.
                if expected_updated_at is None or vote["retry_cycle"] == scope["retry_cycle"]:
                    raise PersistenceFailure("This model vote is already running.")
                # An explicit new cycle can reclaim a vote whose terminal save failed.
                # The parent version and replacement token fence the former worker.
                await connection.execute(
                    "UPDATE classification_vote_attempts SET status = 'interrupted', "
                    "finished_at = NOW(), error = 'Vote replaced by a new retry cycle.' "
                    "WHERE run_id = %s AND voter_id = %s AND attempt = %s AND status = 'running'",
                    (run_id, voter_id, vote["attempts"]),
                )
            if expected_updated_at is not None:
                _check_vote_retry(scope, vote)
            vote = await _fetchone(
                connection,
                """
                UPDATE classification_votes SET status = 'running', attempts = attempts + 1,
                    cycle_attempts = CASE WHEN retry_cycle = %s THEN cycle_attempts + 1 ELSE 1 END,
                    retry_cycle = %s, attempt_token = %s, error = '', errors = '[]'::jsonb,
                    updated_at = NOW() WHERE run_id = %s AND voter_id = %s RETURNING *
            """,
                (scope["retry_cycle"], scope["retry_cycle"], token, run_id, voter_id),
            )
            await connection.execute(
                """
                INSERT INTO classification_vote_attempts
                    (run_id, voter_id, attempt, retry_cycle, model, status, started_at, evidence)
                SELECT %s, %s, %s, %s,
                    COALESCE((SELECT cfg->'body'->>'model'
                        FROM jsonb_array_elements(snapshot->'configuration') cfg
                        WHERE cfg->>'voter_id' = %s LIMIT 1), ''),
                    'running', %s, 'live'
                FROM classification_runs WHERE id = %s
                """,
                (
                    run_id,
                    voter_id,
                    vote["attempts"],
                    scope["retry_cycle"],
                    voter_id,
                    vote["updated_at"],
                    run_id,
                ),
            )
            await _publish_progress(connection, run_id, candidate_id, job_id)
    return vote


def _check_vote_retry(scope, vote):
    policy = RetryPolicy.configured()
    now = datetime.now(timezone.utc)
    if (
        scope["retry_round"] > 0
        and scope["retry_started_at"] is not None
        and now >= scope["retry_started_at"] + timedelta(seconds=policy.window_seconds)
    ):
        raise PageClassificationError(
            "Automatic retry budget exhausted.", code="llm_retry_exhausted"
        )
    errors = [
        Diagnostic(**{key: value for key, value in item.items() if key != "message"})
        for item in vote["errors"]
    ]
    # A provider deadline also applies to a newly authorized manual cycle.
    future = [item for item in errors if item.retry_at and as_datetime(item.retry_at) > now]
    if future:
        raise PageClassificationError("Model retry is not due.", diagnostics=future)
    if vote["retry_cycle"] != scope["retry_cycle"]:
        return
    blocked = [
        item
        for item in errors
        if item.code not in TRANSIENT | {"llm_invalid_response"}
        or vote["cycle_attempts"] >= policy.limit(item.code)
    ]
    if blocked:
        raise PageClassificationError(
            "Model retry budget exhausted.",
            diagnostics=[
                replace(
                    item,
                    recovery="manual" if item.recovery == "automatic" else item.recovery,
                    attempt=vote["cycle_attempts"],
                    max_attempts=policy.limit(item.code),
                )
                for item in blocked
            ],
        )


async def finish_vote(
    run_id,
    voter_id,
    token,
    *,
    response=None,
    error="",
    errors=None,
    candidate_id=None,
    job_id=None,
    expected_updated_at=None,
):
    """Save the vote, attempt history and parent progress in one fenced transaction."""
    status = "succeeded" if response is not None else "error"
    diagnostics = errors or (
        [Diagnostic("processing_failed", "classification", voter_id=voter_id).to_dict()]
        if response is None
        else []
    )
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await _scope(connection, candidate_id, job_id, expected_updated_at)
            await _lock_run(connection, run_id)
            vote = await _fetchone(
                connection,
                "SELECT * FROM classification_votes WHERE run_id = %s AND voter_id = %s",
                (run_id, voter_id),
            )
            if (
                vote is not None
                and vote["last_attempt_token"] == token
                and vote["status"] == status
                and vote["response"] == response
                and vote["error"] == error[:2000]
                and vote["errors"] == diagnostics
            ):
                return  # Exact terminal write already committed; no progress regression.
            row = await _fetchone(
                connection,
                """
                UPDATE classification_votes SET status = %s, response = %s, error = %s, errors = %s,
                    attempt_token = NULL, last_attempt_token = %s, updated_at = NOW()
                WHERE run_id = %s AND voter_id = %s AND status = 'running'
                    AND attempt_token = %s RETURNING voter_id
            """,
                (
                    status,
                    _jsonb(response) if response is not None else None,
                    error[:2000],
                    _jsonb(diagnostics),
                    token,
                    run_id,
                    voter_id,
                    token,
                ),
            )
            if row is None:
                raise PersistenceFailure("Model vote attempt is no longer current.")
            await connection.execute(
                "UPDATE classification_vote_attempts SET status = %s, error = %s, errors = %s, "
                "finished_at = NOW() WHERE run_id = %s AND voter_id = %s "
                "AND attempt = %s AND status = 'running'",
                (status, error[:2000], _jsonb(diagnostics), run_id, voter_id, vote["attempts"]),
            )
            await _publish_progress(connection, run_id, candidate_id, job_id)


async def mark_interrupted_votes_error():
    """Startup recovery under the application's existing single-process policy."""
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            runs = await _fetchall(
                connection,
                """
                SELECT DISTINCT run.id, run.repository_candidate_id, run.collection_job_id
                FROM classification_runs AS run
                JOIN classification_votes AS vote ON vote.run_id = run.id
                WHERE vote.status = 'running'
            """,
            )
            await connection.execute(
                "UPDATE classification_votes SET status = 'error', attempt_token = NULL, "
                "error = 'Vote interrupted by application restart.', "
                "errors = %s, updated_at = NOW() "
                "WHERE status = 'running'",
                (_jsonb([Diagnostic("processing_interrupted", "classification").to_dict()]),),
            )
            await connection.execute(
                "UPDATE classification_vote_attempts SET status = 'interrupted', "
                "finished_at = NOW(), error = 'Vote interrupted by application restart.', "
                "errors = %s WHERE status = 'running'",
                (_jsonb([Diagnostic("processing_interrupted", "classification").to_dict()]),),
            )
            for run in runs:
                if run["repository_candidate_id"] is not None:
                    await _publish_progress(
                        connection, run["id"], run["repository_candidate_id"], None
                    )
                else:
                    jobs = await _fetchall(
                        connection,
                        """
                        SELECT id FROM collection_jobs
                        WHERE COALESCE(classification_root_id, id) = %s AND status = 'running'
                    """,
                        (run["collection_job_id"],),
                    )
                    for job in jobs:
                        await _publish_progress(connection, run["id"], None, job["id"])
