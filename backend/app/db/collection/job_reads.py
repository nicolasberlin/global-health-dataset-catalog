"""Read collection jobs and reconstruct the shared stored-job representation."""

from __future__ import annotations

from uuid import UUID

from app.db.connection import Row, _fetchall, _fetchone, _require_database_pool
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from app.db.serialization import (
    _deserialize_discovery_methods,
    _format_optional_timestamp,
    _format_timestamp,
)


async def get_collection_job(job_id: int) -> dict[str, object] | None:
    """Read an internal job using the same representation as lifecycle writes."""
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _get_collection_job_row(connection, job_id)

    return _collection_job_to_dict(row) if row else None


async def get_collection_job_for_owner(job_id: int, owner_id: str) -> dict[str, object] | None:
    """Read only jobs explicitly associated with one of the owner's candidates."""
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            SELECT job.* FROM collection_jobs AS job
            WHERE job.id = %s AND EXISTS (
                SELECT 1 FROM collection_job_candidates AS association
                JOIN repository_candidates AS candidate
                      ON candidate.id = association.candidate_id
                JOIN search_sessions AS session ON session.id = candidate.search_session_id
                WHERE association.job_id = job.id AND session.owner_id = %s
            )
            """,
            (job_id, validate_owner_id(owner_id)),
        )
        if row is None:
            return None
        job = _collection_job_to_dict(row)
        job["dataset_ids"] = await _job_dataset_ids(connection, job_id)
        return job


async def _get_collection_job_row(connection, job_id: int) -> Row | None:
    return await _fetchone(
        connection,
        """
        SELECT id, source_url, kind, repository_candidate_id,
               status, saved_count, discovered_count,
               analyzed_count, accepted_count, rejected_count,
               invalid_distribution_count, discovery_methods, classification_progress,
               message, error, errors, outcome, collection_coverage, collection_method_summary,
               created_at, updated_at, finished_at, collection_deadline_at
        FROM collection_jobs
        WHERE id = %s
        """,
        (job_id,),
    )


async def _job_dataset_ids(connection, job_id: int) -> list[int]:
    rows = await _fetchall(
        connection,
        """SELECT DISTINCT dataset_id FROM dataset_discovery_observations
           WHERE collection_job_id = %s ORDER BY dataset_id""",
        (job_id,),
    )
    return [int(row["dataset_id"]) for row in rows]


def _collection_job_to_dict(row: Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "source_url": str(row["source_url"]),
        "kind": str(row["kind"]),
        "repository_candidate_id": (
            UUID(str(row["repository_candidate_id"]))
            if row["repository_candidate_id"] is not None
            else None
        ),
        "status": str(row["status"]),
        "coverage": row.get("collection_coverage", {}),
        "method_attempts": row.get("collection_method_summary", []),
        "classification_progress": row.get("classification_progress", {}),
        "saved_count": int(row["saved_count"]),
        "discovered_count": int(row["discovered_count"]),
        "analyzed_count": int(row["analyzed_count"]),
        "accepted_count": int(row["accepted_count"]),
        "rejected_count": int(row["rejected_count"]),
        "invalid_distribution_count": int(row["invalid_distribution_count"]),
        "discovery_methods": _deserialize_discovery_methods(row["discovery_methods"]),
        "message": str(row["message"]),
        "error": str(row["error"]),
        "errors": row.get("errors", []),
        "outcome": row.get("outcome"),
        "created_at": _format_timestamp(row["created_at"]),
        "updated_at": _format_timestamp(row["updated_at"]),
        "finished_at": _format_optional_timestamp(row["finished_at"]),
        "collection_deadline_at": (
            _format_timestamp(row["collection_deadline_at"])
            if row.get("collection_deadline_at") is not None
            else None
        ),
    }
