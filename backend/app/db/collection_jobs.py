from __future__ import annotations

from collector.storage.models import CollectionReport

from .connection import Row, _fetchone, _require_database_pool
from .schema import _require_current_schema
from .serialization import (
    _deserialize_discovery_methods,
    _format_optional_timestamp,
    _format_timestamp,
    _serialize_discovery_methods,
)


async def create_collection_job(source_url: str) -> dict[str, object]:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            INSERT INTO collection_jobs (source_url, status, message)
            VALUES (%s, 'pending', 'Collecte en attente.')
            RETURNING id, source_url, status, saved_count, discovered_count,
                      analyzed_count, accepted_count, rejected_count,
                      invalid_distribution_count, discovery_methods, message,
                      error, created_at, updated_at, finished_at
            """,
            (source_url,),
        )

    if row is None:
        raise RuntimeError("Collection job insert did not return a row.")
    return _collection_job_to_dict(row)


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
                message = 'Collecte en cours.',
                error = '',
                updated_at = NOW(),
                finished_at = NULL
            WHERE id = %s AND status = 'pending'
            RETURNING id, source_url, status, saved_count, discovered_count,
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
    message = _collection_job_done_message(saved_count, report)
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
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
            RETURNING id, source_url, status, saved_count, discovered_count,
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
                message,
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
                message = 'Collecte échouée.',
                error = %s,
                updated_at = NOW(),
                finished_at = NOW()
            WHERE id = %s AND status IN ('pending', 'running')
            RETURNING id, source_url, status, saved_count, discovered_count,
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
        SELECT id, source_url, status, saved_count, discovered_count,
               analyzed_count, accepted_count, rejected_count,
               invalid_distribution_count, discovery_methods, message, error,
               created_at, updated_at, finished_at
        FROM collection_jobs
        WHERE id = %s
        """,
        (job_id,),
    )


def _collection_job_to_dict(row: Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "source_url": str(row["source_url"]),
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
        return f"{saved_count} dataset(s) sauvegardé(s)."
    if report.discovered_count == 0:
        return "Aucune URL candidate découverte."
    if report.analyzed_count == 0:
        return "Aucune page analysée."
    return "Aucun dataset santé avec fichier valide trouvé."
