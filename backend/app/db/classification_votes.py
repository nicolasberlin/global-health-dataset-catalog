"""Individual validated votes, scoped to an owned candidate or a collection retry lineage."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from collector.classification.page import PageClassificationError

from .connection import _fetchall, _fetchone, _require_database_pool
from .serialization import _jsonb


async def prepare_vote_run(snapshot, *, candidate_id=None, job_id=None):
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
            if candidate_id is not None:
                scope = await _fetchone(
                    connection,
                    "SELECT id FROM repository_candidates WHERE id = %s "
                    "AND classification_status = 'classifying'",
                    (candidate_id,),
                )
                column = "repository_candidate_id"
            else:
                scope = await _fetchone(
                    connection,
                    "SELECT COALESCE(classification_root_id, id) AS id FROM collection_jobs "
                    "WHERE id = %s AND status = 'running'",
                    (job_id,),
                )
                column = "collection_job_id"
            if scope is None:
                raise PageClassificationError("Classification is no longer running.")
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


async def claim_vote(run_id, voter_id, *, candidate_id=None, job_id=None):
    token = uuid4()
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await _lock_run(connection, run_id)
            vote = await _fetchone(
                connection,
                "UPDATE classification_votes SET status = 'running', attempts = attempts + 1, "
                "attempt_token = %s, error = '', updated_at = NOW() "
                "WHERE run_id = %s AND voter_id = %s AND status IN ('pending', 'error') "
                "RETURNING *",
                (token, run_id, voter_id),
            )
            if vote is None:
                vote = await _fetchone(
                    connection,
                    "SELECT * FROM classification_votes WHERE run_id = %s AND voter_id = %s",
                    (run_id, voter_id),
                )
                if vote is None or vote["status"] != "succeeded":
                    raise PageClassificationError("This model vote is already running.")
            await _publish_progress(connection, run_id, candidate_id, job_id)
    return vote


async def finish_vote(
    run_id, voter_id, token, *, response=None, error="", candidate_id=None, job_id=None
):
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await _lock_run(connection, run_id)
            row = await _fetchone(
                connection,
                "UPDATE classification_votes SET status = %s, response = %s, error = %s, "
                "attempt_token = NULL, updated_at = NOW() "
                "WHERE run_id = %s AND voter_id = %s AND status = 'running' "
                "AND attempt_token = %s RETURNING voter_id",
                (
                    "succeeded" if response is not None else "error",
                    _jsonb(response) if response is not None else None,
                    error[:2000],
                    run_id,
                    voter_id,
                    token,
                ),
            )
            if row is None:
                raise PageClassificationError("Model vote attempt is no longer current.")
            await _publish_progress(connection, run_id, candidate_id, job_id)


async def _lock_run(connection, run_id):
    await connection.execute(
        "SELECT id FROM classification_runs WHERE id = %s FOR UPDATE",
        (run_id,),
    )


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
                "error = 'Vote interrupted by application restart.', updated_at = NOW() "
                "WHERE status = 'running'"
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
