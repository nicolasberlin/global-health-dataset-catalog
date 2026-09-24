from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.quota_policy import WorkAdmission
from collector.storage.models import CollectionReport
from collector.url_utils import require_http_url

from .api_quotas import lock_work_admission, reserve_work
from .connection import Row, _fetchall, _fetchone, _require_database_pool
from .schema import _require_current_schema
from .search_sessions import _normalized_owner_id
from .serialization import (
    _deserialize_discovery_methods,
    _format_optional_timestamp,
    _format_timestamp,
    _jsonb,
    _serialize_discovery_methods,
)


@dataclass(frozen=True)
class CollectionJobReservation:
    """Result of atomically reserving collection for one repository candidate."""

    job: dict[str, object] | None
    created: bool
    already_collected: bool
    dataset_ids: tuple[int, ...] = ()


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
    """Explicit internal reservation; reads must use get_candidate_collection instead."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            return await _reserve_repository_candidate_collection_job(
                connection, candidate_id, owner_id,
            )


async def _reserve_repository_candidate_collection_job(
    connection: AsyncConnection[DictRow],
    candidate_id: UUID,
    owner_id: str,
) -> CollectionJobReservation:
    """Reserve on the caller's transaction, including candidate associations."""

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
            active_job.classification_progress,
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
                   invalid_distribution_count, discovery_methods, classification_progress,
                   message,
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
            dataset_ids=tuple(await _existing_dataset_ids(connection, source_url)),
        )

    if reservation_state["id"] is not None:
        await _associate_job_candidate(connection, reservation_state["id"], candidate_id)
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
    await _associate_job_candidate(connection, new_job["id"], candidate_id)
    return CollectionJobReservation(
        job=_collection_job_to_dict(new_job),
        created=True,
        already_collected=False,
    )


async def _associate_job_candidate(connection, job_id: int, candidate_id: UUID) -> None:
    await connection.execute(
        """
        INSERT INTO collection_job_candidates (job_id, candidate_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
        """,
        (job_id, candidate_id),
    )


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
            (job_id, _normalized_owner_id(owner_id)),
        )
        if row is None:
            return None
        job = _collection_job_to_dict(row)
        job["dataset_ids"] = await _job_dataset_ids(connection, job_id)
        return job


async def _job_dataset_ids(connection, job_id: int) -> list[int]:
    rows = await _fetchall(
        connection,
        """SELECT DISTINCT dataset_id FROM dataset_discovery_observations
           WHERE collection_job_id = %s ORDER BY dataset_id""",
        (job_id,),
    )
    return [int(row["dataset_id"]) for row in rows]


async def retry_collection_job_for_owner(
    job_id: int, owner_id: str, *, admission: WorkAdmission | None = None,
) -> dict | None:
    """Requeue an owned failed job, keeping its validated votes and associations."""
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await lock_work_admission(connection, admission)
            job = await _fetchone(connection, """
                SELECT job.* FROM collection_jobs AS job
                WHERE job.id = %s AND EXISTS (
                    SELECT 1 FROM collection_job_candidates AS association
                    JOIN repository_candidates AS candidate
                      ON candidate.id = association.candidate_id
                    JOIN search_sessions AS session ON session.id = candidate.search_session_id
                    WHERE association.job_id = job.id AND session.owner_id = %s
                )
            """, (job_id, _normalized_owner_id(owner_id)))
            if job is None:
                return None
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (job["source_url"],),
            )
            job = await _fetchone(connection,
                "SELECT * FROM collection_jobs WHERE id = %s FOR UPDATE", (job_id,))
            if job["status"] in {"pending", "running"}:
                return _collection_job_to_dict(job)
            if job["status"] != "error":
                raise ValueError("Only a failed collection can be retried.")
            active = await _fetchone(connection, """
                SELECT id FROM collection_jobs WHERE source_url = %s
                AND status IN ('pending', 'running') AND id <> %s
            """, (job["source_url"], job_id))
            if active:
                raise ValueError("Another collection is already running for this page.")
            await reserve_work(connection, admission, amount=1)
            row = await _fetchone(connection, """
                UPDATE collection_jobs SET status = 'pending', error = '',
                    message = 'Collection pending.', finished_at = NULL, updated_at = NOW()
                WHERE id = %s RETURNING *
            """, (job_id,))
            return _collection_job_to_dict(row)


async def _existing_dataset_ids(connection, source_url: str) -> list[int]:
    rows = await _fetchall(
        connection,
        """SELECT dataset.id FROM collected_datasets AS dataset
           WHERE dataset.dataset_url = %s OR EXISTS (
               SELECT 1 FROM dataset_discovery_observations AS observation
               WHERE observation.dataset_id = dataset.id AND observation.source_url = %s
           ) ORDER BY dataset.id""",
        (source_url, source_url),
    )
    return [int(row["id"]) for row in rows]


async def mark_interrupted_collection_jobs_error() -> int:
    """Fail interrupted running jobs; pending jobs remain available to the worker.

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
            WHERE status = 'running'
            RETURNING id
            """,
        )

    return len(rows)


async def claim_pending_collection_job() -> dict[str, object] | None:
    """Claim one persisted job only when a worker has a free execution slot."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            UPDATE collection_jobs
            SET status = 'running', message = 'Collection in progress.', updated_at = NOW()
            WHERE id = (
                SELECT id FROM collection_jobs WHERE status = 'pending'
                ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) AND status = 'pending'
            RETURNING *
            """,
        )
    return _collection_job_to_dict(row) if row else None


async def get_candidate_collection(
    candidate_id: UUID, owner_id: str,
) -> CollectionJobReservation | None:
    """Read existing follow-up without reserving, associating, or retrying a job.

    The latest job associated with this candidate wins over unrelated work at
    the same URL. Legacy accepted candidates without follow-up stay explicit.
    """

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            SELECT existing_job.*, candidate.url AS candidate_url, EXISTS (
                SELECT 1 FROM collected_datasets AS dataset
                WHERE dataset.dataset_url = candidate.url OR EXISTS (
                    SELECT 1 FROM dataset_discovery_observations AS observation
                    WHERE observation.dataset_id = dataset.id
                      AND observation.source_url = candidate.url
                )
            ) AS already_collected
            FROM repository_candidates AS candidate
            JOIN search_sessions AS session ON session.id = candidate.search_session_id
            LEFT JOIN LATERAL (
                SELECT job.* FROM collection_jobs AS job
                JOIN collection_job_candidates AS association ON association.job_id = job.id
                WHERE association.candidate_id = candidate.id
                ORDER BY job.id DESC LIMIT 1
            ) AS existing_job ON TRUE
            WHERE candidate.id = %s AND session.owner_id = %s
              AND candidate.classification_status = 'accepted'
            """,
            (candidate_id, _normalized_owner_id(owner_id)),
        )
        if row is None:
            return None
        if row["id"] is not None:
            ids = await _job_dataset_ids(connection, int(row["id"]))
            job = _collection_job_to_dict(row)
            job["dataset_ids"] = ids
            return CollectionJobReservation(job, False, False, tuple(ids))
        ids = await _existing_dataset_ids(connection, str(row["candidate_url"]))
        return CollectionJobReservation(None, False, bool(ids), tuple(ids))


async def _insert_collection_job(
    connection: AsyncConnection[DictRow],
    source_url: str,
    *,
    kind: str = "source",
    repository_candidate_id: UUID | None = None,
) -> Row | None:
    previous = await _fetchone(connection, """
        SELECT job.status, COALESCE(job.classification_root_id, job.id) AS root_id
        FROM collection_jobs AS job
        WHERE job.source_url = %s AND job.kind = %s AND (
            (%s::uuid IS NULL AND job.repository_candidate_id IS NULL) OR EXISTS (
                SELECT 1 FROM collection_job_candidates AS association
                WHERE association.job_id = job.id AND association.candidate_id = %s
            )
        ) ORDER BY job.id DESC LIMIT 1
    """, (source_url, kind, repository_candidate_id, repository_candidate_id))
    root_id = previous["root_id"] if previous and previous["status"] == "error" else None
    return await _fetchone(
        connection,
        """
        INSERT INTO collection_jobs (
            source_url, kind, repository_candidate_id, classification_root_id, status, message
        )
        VALUES (%s, %s, %s, %s, 'pending', 'Collection pending.')
        RETURNING id, source_url, kind, repository_candidate_id,
                  status, saved_count, discovered_count,
                  analyzed_count, accepted_count, rejected_count,
                  invalid_distribution_count, discovery_methods, classification_progress,
                  message,
                  error, created_at, updated_at, finished_at
        """,
        (source_url, kind, repository_candidate_id, root_id),
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
                      invalid_distribution_count, discovery_methods, classification_progress,
                      message,
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
            validation_failures = %s,
            message = %s,
            error = '',
            updated_at = NOW(),
            finished_at = NOW()
        WHERE id = %s AND status = 'running'
        RETURNING id, source_url, kind, repository_candidate_id,
                  status, saved_count, discovered_count,
                  analyzed_count, accepted_count, rejected_count,
                  invalid_distribution_count, discovery_methods, classification_progress,
                  message,
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
            _jsonb([asdict(result) for result in report.validation_failures]),
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
                      invalid_distribution_count, discovery_methods, classification_progress,
                      message,
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
               invalid_distribution_count, discovery_methods, classification_progress,
               message, error,
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
