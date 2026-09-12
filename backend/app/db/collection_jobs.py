from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from collector.storage.models import CollectionReport
from collector.url_utils import require_http_url

from .connection import Row, _fetchall, _fetchone, _require_database_pool
from .schema import _require_current_schema
from .search_sessions import _normalized_owner_id
from .serialization import (
    _deserialize_discovery_methods,
    _format_optional_timestamp,
    _format_timestamp,
    _serialize_discovery_methods,
)


@dataclass(frozen=True)
class CollectionJobReservation:
    """Result of atomically reserving collection for one repository candidate."""

    job: dict[str, object] | None
    created: bool
    already_collected: bool


async def create_collection_job(source_url: str) -> dict[str, object]:
    source_url = require_http_url(source_url)
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _insert_collection_job(connection, source_url)

    if row is None:
        raise RuntimeError("Collection job insert did not return a row.")
    return _collection_job_to_dict(row)


async def reserve_repository_candidate_collection_job(
    candidate_id: UUID,
    owner_id: str,
) -> CollectionJobReservation:
    """Create one pending job unless the accepted candidate is already handled.

    Locking the candidate serializes the check-and-insert sequence, while the
    partial unique index independently enforces one active job per candidate.
    Only pending or running jobs block a new attempt; terminal jobs remain as
    immutable attempt history.
    """

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            candidate = await _fetchone(
                connection,
                """
                SELECT candidate.id, candidate.url, candidate.classification_status
                FROM repository_candidates AS candidate
                JOIN search_sessions AS session
                  ON session.id = candidate.search_session_id
                WHERE candidate.id = %s AND session.owner_id = %s
                FOR UPDATE OF candidate
                """,
                (candidate_id, _normalized_owner_id(owner_id)),
            )
            if candidate is None:
                raise ValueError("Repository candidate not found.")
            if str(candidate["classification_status"]) != "accepted":
                raise ValueError("Only an accepted candidate can be collected.")

            source_url = require_http_url(str(candidate["url"]))
            # Different searches can persist different candidate IDs for the
            # same URL, so URL-level serialization is also required.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (source_url,),
            )
            reservation_state = await _fetchone(
                connection,
                """
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM collected_datasets AS dataset
                        WHERE dataset.dataset_url = %s
                           OR EXISTS (
                               SELECT 1
                               FROM dataset_discovery_observations AS observation
                               WHERE observation.dataset_id = dataset.id
                                 AND observation.source_url = %s
                           )
                    ) AS already_collected,
                    active_job.id,
                    active_job.source_url,
                    active_job.kind,
                    active_job.repository_candidate_id,
                    active_job.status,
                    active_job.saved_count,
                    active_job.discovered_count,
                    active_job.analyzed_count,
                    active_job.accepted_count,
                    active_job.rejected_count,
                    active_job.invalid_distribution_count,
                    active_job.discovery_methods,
                    active_job.message,
                    active_job.error,
                    active_job.created_at,
                    active_job.updated_at,
                    active_job.finished_at
                FROM (VALUES (1)) AS singleton(value)
                LEFT JOIN LATERAL (
                    SELECT id, source_url, kind, repository_candidate_id,
                           status, saved_count, discovered_count,
                           analyzed_count, accepted_count, rejected_count,
                           invalid_distribution_count, discovery_methods, message,
                           error, created_at, updated_at, finished_at
                    FROM collection_jobs
                    WHERE (
                        repository_candidate_id = %s
                        OR (kind = 'repository_candidate' AND source_url = %s)
                    )
                      AND status IN ('pending', 'running')
                    ORDER BY id DESC
                    LIMIT 1
                ) AS active_job ON TRUE
                """,
                (source_url, source_url, candidate_id, source_url),
            )
            if reservation_state is None:
                raise RuntimeError("Automatic collection lookup returned no row.")
            if bool(reservation_state["already_collected"]):
                return CollectionJobReservation(
                    job=None,
                    created=False,
                    already_collected=True,
                )

            if reservation_state["id"] is not None:
                return CollectionJobReservation(
                    job=_collection_job_to_dict(reservation_state),
                    created=False,
                    already_collected=False,
                )

            new_job = await _insert_collection_job(
                connection,
                source_url,
                kind="repository_candidate",
                repository_candidate_id=candidate_id,
            )
            if new_job is None:
                raise RuntimeError("Collection job insert did not return a row.")
            return CollectionJobReservation(
                job=_collection_job_to_dict(new_job),
                created=True,
                already_collected=False,
            )


async def mark_interrupted_collection_jobs_error() -> int:
    """Fail process-local jobs left active by a previous application process.

    This recovery is valid only while the backend runs as one application
    process. A multi-process deployment requires durable ownership and leases so
    one process cannot invalidate work that another process still owns.
    """

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _fetchall(
            connection,
            """
            UPDATE collection_jobs
            SET status = 'error',
                message = 'Collection interrupted.',
                error = 'Collection interrupted by application restart.',
                updated_at = NOW(),
                finished_at = NOW()
            WHERE status IN ('pending', 'running')
            RETURNING id
            """,
        )

    return len(rows)


async def _insert_collection_job(
    connection: AsyncConnection[DictRow],
    source_url: str,
    *,
    kind: str = "source",
    repository_candidate_id: UUID | None = None,
) -> Row | None:
    return await _fetchone(
        connection,
        """
        INSERT INTO collection_jobs (
            source_url, kind, repository_candidate_id, status, message
        )
        VALUES (%s, %s, %s, 'pending', 'Collection pending.')
        RETURNING id, source_url, kind, repository_candidate_id,
                  status, saved_count, discovered_count,
                  analyzed_count, accepted_count, rejected_count,
                  invalid_distribution_count, discovery_methods, message,
                  error, created_at, updated_at, finished_at
        """,
        (source_url, kind, repository_candidate_id),
    )


async def get_collection_job(job_id: int) -> dict[str, object] | None:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _get_collection_job_row(connection, job_id)

    return _collection_job_to_dict(row) if row else None


async def mark_collection_job_running(job_id: int) -> dict[str, object] | None:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            UPDATE collection_jobs
            SET status = 'running',
                saved_count = 0,
                discovered_count = 0,
                analyzed_count = 0,
                accepted_count = 0,
                rejected_count = 0,
                invalid_distribution_count = 0,
                discovery_methods = '[]'::jsonb,
                message = 'Collection in progress.',
                error = '',
                updated_at = NOW(),
                finished_at = NULL
            WHERE id = %s AND status = 'pending'
            RETURNING id, source_url, kind, repository_candidate_id,
                      status, saved_count, discovered_count,
                      analyzed_count, accepted_count, rejected_count,
                      invalid_distribution_count, discovery_methods, message,
                      error, created_at, updated_at, finished_at
            """,
            (job_id,),
        )

    return _collection_job_to_dict(row) if row else None


async def mark_collection_job_done(
    job_id: int,
    saved_count: int,
    report: CollectionReport | None = None,
) -> dict[str, object] | None:
    report = report or CollectionReport()
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        return await _mark_collection_job_done(connection, job_id, saved_count, report)


async def _mark_collection_job_done(
    connection: AsyncConnection[DictRow],
    job_id: int,
    saved_count: int,
    report: CollectionReport,
) -> dict[str, object] | None:
    row = await _fetchone(
        connection,
        """
        UPDATE collection_jobs
        SET status = 'done',
            saved_count = %s,
            discovered_count = %s,
            analyzed_count = %s,
            accepted_count = %s,
            rejected_count = %s,
            invalid_distribution_count = %s,
            discovery_methods = %s,
            message = %s,
            error = '',
            updated_at = NOW(),
            finished_at = NOW()
        WHERE id = %s AND status = 'running'
        RETURNING id, source_url, kind, repository_candidate_id,
                  status, saved_count, discovered_count,
                  analyzed_count, accepted_count, rejected_count,
                  invalid_distribution_count, discovery_methods, message,
                  error, created_at, updated_at, finished_at
        """,
        (
            saved_count,
            report.discovered_count,
            report.analyzed_count,
            report.accepted_count,
            report.rejected_count,
            report.invalid_distribution_count,
            _serialize_discovery_methods(report.discovery_methods),
            _collection_job_done_message(saved_count, report),
            job_id,
        ),
    )
    return _collection_job_to_dict(row) if row else None


async def mark_collection_job_error(
    job_id: int,
    error: str,
) -> dict[str, object] | None:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            UPDATE collection_jobs
            SET status = 'error',
                message = 'Collection failed.',
                error = %s,
                updated_at = NOW(),
                finished_at = NOW()
            WHERE id = %s AND status IN ('pending', 'running')
            RETURNING id, source_url, kind, repository_candidate_id,
                      status, saved_count, discovered_count,
                      analyzed_count, accepted_count, rejected_count,
                      invalid_distribution_count, discovery_methods, message,
                      error, created_at, updated_at, finished_at
            """,
            (error, job_id),
        )

    return _collection_job_to_dict(row) if row else None


async def _get_collection_job_row(connection, job_id: int) -> Row | None:
    return await _fetchone(
        connection,
        """
        SELECT id, source_url, kind, repository_candidate_id,
               status, saved_count, discovered_count,
               analyzed_count, accepted_count, rejected_count,
               invalid_distribution_count, discovery_methods, message, error,
               created_at, updated_at, finished_at
        FROM collection_jobs
        WHERE id = %s
        """,
        (job_id,),
    )


async def _lock_running_collection_job(
    connection: AsyncConnection[DictRow],
    job_id: int,
) -> Row | None:
    return await _fetchone(
        connection,
        """
        SELECT id, source_url
        FROM collection_jobs
        WHERE id = %s AND status = 'running'
        FOR UPDATE
        """,
        (job_id,),
    )


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
        "saved_count": int(row["saved_count"]),
        "discovered_count": int(row["discovered_count"]),
        "analyzed_count": int(row["analyzed_count"]),
        "accepted_count": int(row["accepted_count"]),
        "rejected_count": int(row["rejected_count"]),
        "invalid_distribution_count": int(row["invalid_distribution_count"]),
        "discovery_methods": _deserialize_discovery_methods(row["discovery_methods"]),
        "message": str(row["message"]),
        "error": str(row["error"]),
        "created_at": _format_timestamp(row["created_at"]),
        "updated_at": _format_timestamp(row["updated_at"]),
        "finished_at": _format_optional_timestamp(row["finished_at"]),
    }


def _collection_job_done_message(saved_count: int, report: CollectionReport) -> str:
    if saved_count:
        return f"{saved_count} dataset(s) saved."
    if report.discovered_count == 0:
        return "No candidate URL was discovered."
    if report.analyzed_count == 0:
        return "No page was analyzed."
    return "No health dataset with a valid file was found."
