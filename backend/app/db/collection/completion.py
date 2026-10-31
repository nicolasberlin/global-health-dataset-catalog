"""Finalize collection results atomically or update only an existing job report."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.catalog.datasets import _save_collected_dataset
from app.db.collection.job_reads import _collection_job_to_dict, _job_dataset_ids
from app.db.collection.jobs import _lock_running_collection_job
from app.db.collection.traces.sanitization import safe_observation
from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.schema import _require_current_schema
from app.db.serialization import _jsonb, _serialize_discovery_methods
from collector.storage.metadata import enrich_from_repository
from collector.storage.models import CollectionReport, CollectionResult


async def complete_collection_job(
    job_id: int,
    collection_result: CollectionResult,
    *, expected_updated_at: datetime | None = None,
) -> dict[str, object] | None:
    """Save all collected datasets and mark their running job done atomically.

    Collection and LLM calls have already finished before this function opens
    one connection and one transaction. Locking supplies the authoritative
    source URL from the job. Any dataset write or job-state failure rolls back
    every dataset write and prevents the job from becoming ``done``.

    Workers pass the claim's exact updated_at as a version. A guarded call
    returns None when that version is no longer active, including when a prior
    commit succeeded but its acknowledgement was lost. No datasets are rewritten.
    """

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            job = await _lock_running_collection_job(connection, job_id)
            if expected_updated_at is not None and (
                job is None or job["updated_at"] != expected_updated_at
            ):
                # Already committed (possibly without acknowledgement), or superseded.
                return None
            if job is None:
                raise RuntimeError(
                    f"Collection job {job_id} is not running and cannot be completed."
                )

            source_url = str(job["source_url"])
            datasets = collection_result.datasets
            if len(datasets) == 1:
                candidates = await _fetchall(
                    connection,
                    """SELECT candidate.url, candidate.publication_date, candidate.doi,
                              candidate.metadata, candidate.source AS provider
                       FROM collection_job_candidates AS association
                       JOIN repository_candidates AS candidate
                         ON candidate.id = association.candidate_id
                       JOIN collection_jobs AS job ON job.id = association.job_id
                       WHERE job.id = %s AND job.kind = 'repository_candidate'
                         AND candidate.url = job.source_url
                       ORDER BY candidate.created_at, candidate.id""",
                    (job_id,),
                )
                dataset = datasets[0]
                for candidate in candidates:
                    dataset = enrich_from_repository(dataset, candidate)
                datasets = [dataset]
            saved_datasets = [
                await _save_collected_dataset(
                    connection,
                    source_url,
                    dataset,
                    job_id,
                )
                for dataset in datasets
            ]
            completed_job = await _mark_collection_job_done(
                connection,
                job_id,
                max(len(saved_datasets), len(await _job_dataset_ids(connection, job_id))),
                collection_result.report,
            )
            if completed_job is None:
                raise RuntimeError(
                    f"Collection job {job_id} is not running and cannot be completed."
                )

    return completed_job


async def mark_collection_job_done(
    job_id: int,
    saved_count: int,
    report: CollectionReport | None = None,
) -> dict[str, object] | None:
    """Save only job state and report fields; this operation does not store datasets."""
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
            errors = %s, outcome = %s,
            collection_coverage = %s, collection_method_summary = %s,
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
                  error, errors, outcome, created_at, updated_at, finished_at,
                  collection_deadline_at, collection_coverage, collection_method_summary
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
            _jsonb([item.to_dict() for item in report.errors]),
            "incomplete"
            if report.errors or report.verification_complete is not True
            else "results"
            if saved_count
            else "empty",
            _jsonb(report.coverage),
            _jsonb([safe_observation(step) for step in report.method_attempts]),
            _collection_job_done_message(saved_count, report),
            job_id,
        ),
    )
    return _collection_job_to_dict(row) if row else None


def _collection_job_done_message(saved_count: int, report: CollectionReport) -> str:
    if report.errors:
        return f"Collection incomplete; {saved_count} dataset(s) saved."
    if saved_count:
        return f"{saved_count} dataset(s) saved."
    if report.discovered_count == 0:
        return "No candidate URL was discovered."
    if report.analyzed_count == 0:
        return "No page was analyzed."
    return "No health dataset with a valid file was found."
