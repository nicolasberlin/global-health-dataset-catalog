"""Create, claim, transition and recover persisted collection jobs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.collection.job_reads import _collection_job_to_dict
from app.db.connection import Row, _fetchall, _fetchone, _require_database_pool
from app.db.execution.worker_claims import read_worker_claim, record_worker_claim
from app.db.schema import _require_current_schema
from app.db.serialization import (
    _jsonb,
)
from collector.config import configured_collection_budget_seconds
from collector.diagnostics import Diagnostic
from collector.url_utils import require_http_url


async def create_collection_job(source_url: str) -> dict[str, object]:
    """Create a pending source job without executing collection work."""
    source_url = require_http_url(source_url)
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _insert_collection_job(connection, source_url)

    if row is None:
        raise RuntimeError("Collection job insert did not return a row.")
    return _collection_job_to_dict(row)


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
                errors = %s, outcome = 'incomplete',
                updated_at = NOW(),
                finished_at = NOW()
            WHERE status = 'running'
            RETURNING id
            """,
            (_jsonb([Diagnostic("processing_interrupted", "collection").to_dict()]),),
        )

        if rows:
            await connection.execute(
                """
                UPDATE collection_method_attempts SET observation = observation ||
                    '{"status":"failed","code":"processing_interrupted"}'::jsonb
                WHERE job_id = ANY(%s) AND observation->>'status' = 'running'
            """,
                ([r["id"] for r in rows],),
            )

    return len(rows)


async def claim_pending_collection_job(
    *,
    claim_token: UUID | None = None,
) -> dict[str, object] | None:
    """Acquire or recover the same job after an ambiguous database commit."""

    claim_token = claim_token or uuid4()
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            receipt = await read_worker_claim(connection, claim_token, "collection")
            if receipt is not None:
                row = await _fetchone(
                    connection,
                    """SELECT * FROM collection_jobs
                       WHERE id = %s AND status = 'running' AND updated_at = %s""",
                    (int(receipt["resource_id"]), receipt["claim_version"]),
                )
                return _collection_job_to_dict(row) if row else None
            row = await _fetchone(
                connection,
                """
                UPDATE collection_jobs
                SET status = 'running', message = 'Collection in progress.', updated_at = NOW(),
                    retry_started_at = COALESCE(retry_started_at, NOW()),
                    collection_deadline_at = COALESCE(
                        collection_deadline_at, NOW() + %s * INTERVAL '1 second'
                    ),
                    next_retry_at = NULL, errors = '[]'::jsonb
                WHERE id = (
                    SELECT id FROM collection_jobs WHERE status = 'pending'
                        AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                    ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
                ) AND status = 'pending'
                RETURNING *
                """,
                (configured_collection_budget_seconds(),),
            )
            if row is not None:
                await record_worker_claim(
                    connection,
                    claim_token,
                    "collection",
                    row["id"],
                    row["updated_at"],
                )
    return _collection_job_to_dict(row) if row else None


async def _insert_collection_job(
    connection: AsyncConnection[DictRow],
    source_url: str,
    *,
    kind: str = "source",
    repository_candidate_id: UUID | None = None,
) -> Row | None:
    previous = await _fetchone(
        connection,
        """
        SELECT job.status, COALESCE(job.classification_root_id, job.id) AS root_id
        FROM collection_jobs AS job
        WHERE job.source_url = %s AND job.kind = %s AND (
            (%s::uuid IS NULL AND job.repository_candidate_id IS NULL) OR EXISTS (
                SELECT 1 FROM collection_job_candidates AS association
                WHERE association.job_id = job.id AND association.candidate_id = %s
            )
        ) ORDER BY job.id DESC LIMIT 1
    """,
        (source_url, kind, repository_candidate_id, repository_candidate_id),
    )
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
                  error, errors, outcome, created_at, updated_at, finished_at,
                  collection_deadline_at, collection_coverage, collection_method_summary
        """,
        (source_url, kind, repository_candidate_id, root_id),
    )


async def mark_collection_job_running(job_id: int) -> dict[str, object] | None:
    """Start a pending job and initialize its collection deadline and progress fields."""
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            UPDATE collection_jobs
            SET status = 'running',
                collection_deadline_at = COALESCE(
                    collection_deadline_at, NOW() + %s * INTERVAL '1 second'
                ),
                saved_count = 0,
                discovered_count = 0,
                analyzed_count = 0,
                accepted_count = 0,
                rejected_count = 0,
                invalid_distribution_count = 0,
                discovery_methods = '[]'::jsonb,
                message = 'Collection in progress.',
                error = '', errors = '[]'::jsonb, outcome = NULL,
                    collection_coverage = '{}'::jsonb, collection_method_summary = '[]'::jsonb,
                updated_at = NOW(),
                finished_at = NULL
            WHERE id = %s AND status = 'pending'
            RETURNING id, source_url, kind, repository_candidate_id,
                      status, saved_count, discovered_count,
                      analyzed_count, accepted_count, rejected_count,
                      invalid_distribution_count, discovery_methods, classification_progress,
                      message,
                      error, errors, outcome, created_at, updated_at, finished_at,
                      collection_deadline_at, collection_coverage, collection_method_summary
            """,
            (configured_collection_budget_seconds(), job_id),
        )

    return _collection_job_to_dict(row) if row else None


async def mark_collection_job_error(
    job_id: int,
    error: str,
    *,
    errors: list[dict] | None = None,
    expected_updated_at: datetime | None = None,
) -> dict[str, object] | None:
    """Fail a pending or running job without overwriting a superseding claim."""
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            UPDATE collection_jobs
            SET status = 'error',
                message = 'Collection failed.',
                error = %s, errors = %s, outcome = 'incomplete',
                updated_at = NOW(),
                finished_at = NOW()
            WHERE id = %s AND status IN ('pending', 'running')
              AND (%s::timestamptz IS NULL OR updated_at = %s)
            RETURNING id, source_url, kind, repository_candidate_id,
                      status, saved_count, discovered_count,
                      analyzed_count, accepted_count, rejected_count,
                      invalid_distribution_count, discovery_methods, classification_progress,
                      message,
                      error, errors, outcome, created_at, updated_at, finished_at,
                      collection_deadline_at, collection_coverage, collection_method_summary
            """,
            (
                error,
                _jsonb(errors or [Diagnostic("processing_failed", "collection").to_dict()]),
                job_id,
                expected_updated_at,
                expected_updated_at,
            ),
        )

    return _collection_job_to_dict(row) if row else None


async def _lock_running_collection_job(
    connection: AsyncConnection[DictRow],
    job_id: int,
) -> Row | None:
    return await _fetchone(
        connection,
        """
        SELECT id, source_url, updated_at
        FROM collection_jobs
        WHERE id = %s AND status = 'running'
        FOR UPDATE
        """,
        (job_id,),
    )
