"""Read bounded, owner-scoped vote attempt history for candidates and collections."""

from __future__ import annotations

from app.db.collection.job_reads import get_collection_job_for_owner
from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.owner_ids import validate_owner_id
from app.db.public_history import HistoryPage, PublicVoteAttempt


async def read_candidate_vote_history(candidate_id, owner_id, *, limit=100, offset=0):
    """Read bounded vote attempts after verifying ownership of the candidate."""
    async with _require_database_pool().connection() as connection:
        candidate = await _fetchone(
            connection,
            "SELECT c.id FROM repository_candidates c JOIN search_sessions s "
            "ON s.id = c.search_session_id WHERE c.id = %s AND s.owner_id = %s",
            (candidate_id, validate_owner_id(owner_id)),
        )
    if candidate is None:
        return None
    return await _read_vote_history(
        "repository_candidate_id", candidate_id, limit=limit, offset=offset
    )


async def read_collection_vote_history(job_id, owner_id, *, limit=100, offset=0):
    """Read owned collection votes across their shared retry lineage."""
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
