"""Individual validated votes, scoped to an owned candidate or a collection retry lineage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.retry_policy import TRANSIENT, RetryPolicy, as_datetime
from collector.classification.page import PageClassificationError
from collector.diagnostics import Diagnostic, PersistenceFailure

from .connection import _fetchall, _fetchone, _require_database_pool
from .public_history import HistoryPage, PublicVoteAttempt
from .serialization import _jsonb


async def prepare_vote_run(snapshot, *, candidate_id=None, job_id=None, expected_updated_at=None):
    if (candidate_id is None) == (job_id is None):
        raise ValueError("Exactly one classification scope is required.")
    fingerprint = hashlib.sha256(
        json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    voter_ids = [item["voter_id"] for item in snapshot["configuration"]]
    if not voter_ids or len(voter_ids) != len(set(voter_ids)):
        raise ValueError("Vote identifiers must be non-empty and unique.")
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            scope = await _scope(connection, candidate_id, job_id, expected_updated_at)
            column = "repository_candidate_id" if candidate_id is not None else "collection_job_id"
            await connection.execute(
                f"INSERT INTO classification_runs (id, {column}, fingerprint, snapshot) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (uuid4(), scope["id"], fingerprint, _jsonb(snapshot)),
            )
            run = await _fetchone(
                connection,
                f"SELECT id FROM classification_runs WHERE {column} = %s AND fingerprint = %s "
                "FOR UPDATE",
                (scope["id"], fingerprint),
            )
            await connection.execute(
                "INSERT INTO classification_votes (run_id, voter_id) "
                "SELECT %s, unnest(%s::text[]) ON CONFLICT DO NOTHING",
                (run["id"], voter_ids),
            )
            await _publish_progress(connection, run["id"], candidate_id, job_id)
    return run["id"]


async def claim_vote(
    run_id, voter_id, *, candidate_id=None, job_id=None, expected_updated_at=None, token=None
):
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


async def _scope(connection, candidate_id, job_id, version):
    if (candidate_id is None) == (job_id is None):
        raise ValueError("Exactly one classification scope is required.")
    table, column, status = (
        ("repository_candidates", "classification_status", "classifying")
        if candidate_id is not None
        else ("collection_jobs", "status", "running")
    )
    scope = await _fetchone(
        connection,
        f"SELECT * FROM {table} WHERE id = %s FOR UPDATE",
        (candidate_id if candidate_id is not None else job_id,),
    )
    if (
        scope is None
        or scope[column] != status
        or (version is not None and scope["updated_at"] != version)
    ):
        raise PersistenceFailure("Classification is no longer running.")
    if job_id is not None:
        scope["id"] = scope["classification_root_id"] or scope["id"]
    return scope


async def _lock_run(connection, run_id):
    await connection.execute(
        "SELECT id FROM classification_runs WHERE id = %s FOR UPDATE",
        (run_id,),
    )


async def read_candidate_vote_history(candidate_id, owner_id, *, limit=100, offset=0):
    from .search_sessions import _normalized_owner_id

    async with _require_database_pool().connection() as connection:
        candidate = await _fetchone(
            connection,
            "SELECT c.id FROM repository_candidates c JOIN search_sessions s "
            "ON s.id = c.search_session_id WHERE c.id = %s AND s.owner_id = %s",
            (candidate_id, _normalized_owner_id(owner_id)),
        )
    if candidate is None:
        return None
    return await _read_vote_history(
        "repository_candidate_id", candidate_id, limit=limit, offset=offset
    )


async def read_collection_vote_history(job_id, owner_id, *, limit=100, offset=0):
    from .collection_jobs import get_collection_job_for_owner

    job = await get_collection_job_for_owner(job_id, owner_id)
    if job is None:
        return None
    async with _require_database_pool().connection() as connection:
        root = await _fetchone(
            connection,
            "SELECT COALESCE(classification_root_id, id) AS id FROM collection_jobs WHERE id = %s",
            (job_id,),
        )
    if root is None:
        return None
    return await _read_vote_history("collection_job_id", root["id"], limit=limit, offset=offset)


async def _read_vote_history(column, scope_id, *, limit=100, offset=0):
    page = HistoryPage(limit, offset)
    if column not in {"repository_candidate_id", "collection_job_id"}:
        raise ValueError("Unsupported vote history scope.")
    async with _require_database_pool().connection() as connection:
        rows = await _fetchall(
            connection,
            "SELECT a.run_id, a.voter_id, a.attempt, a.retry_cycle, a.model, a.status, "
            "a.started_at, a.finished_at, a.errors, a.evidence "
            "FROM classification_vote_attempts a JOIN classification_runs r "
            f"ON r.id = a.run_id WHERE r.{column} = %s "
            "ORDER BY COALESCE(a.started_at, a.finished_at) DESC NULLS LAST, "
            "a.run_id, a.voter_id, a.attempt DESC LIMIT %s OFFSET %s",
            (scope_id, page.limit + 1, page.offset),
        )
    return {
        "attempts": [
            PublicVoteAttempt.from_row(row).to_dict() for row in reversed(rows[: page.limit])
        ],
        **page.metadata(len(rows) > page.limit),
    }


async def _publish_progress(connection, run_id, candidate_id, job_id):
    counts = await _fetchone(
        connection,
        "SELECT COUNT(*)::integer AS total, "
        "COUNT(*) FILTER (WHERE status = 'succeeded')::integer AS succeeded, "
        "COUNT(*) FILTER (WHERE status = 'error')::integer AS failed "
        "FROM classification_votes WHERE run_id = %s",
        (run_id,),
    )
    if candidate_id is not None:
        await connection.execute(
            "UPDATE repository_candidates SET classification_progress = %s WHERE id = %s",
            (_jsonb(counts), candidate_id),
        )
    else:
        await connection.execute(
            "UPDATE collection_jobs SET classification_progress = %s WHERE id = %s",
            (_jsonb(counts), job_id),
        )


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
