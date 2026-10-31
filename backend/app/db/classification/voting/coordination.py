"""Connection-taking locks and progress updates shared by vote runs and attempts."""

from __future__ import annotations

from app.db.connection import _fetchone
from app.db.serialization import _jsonb
from collector.diagnostics import PersistenceFailure


async def _scope(connection, candidate_id, job_id, version):
    """Lock the active parent version and resolve its reusable collection vote lineage."""
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
    """Lock the vote run after its parent; callers keep the same connection and transaction."""
    await connection.execute(
        "SELECT id FROM classification_runs WHERE id = %s FOR UPDATE",
        (run_id,),
    )


async def _publish_progress(connection, run_id, candidate_id, job_id):
    """Update stored vote counts without changing the parent claim version."""
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
