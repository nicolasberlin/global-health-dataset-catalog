from __future__ import annotations

from datetime import datetime

from collector.storage.metadata import enrich_from_repository
from collector.storage.models import CollectionResult

from .collected_datasets import _save_collected_dataset
from .collection_jobs import _lock_running_collection_job, _mark_collection_job_done
from .connection import _fetchall, _require_database_pool
from .schema import _require_current_schema


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
                len(saved_datasets),
                collection_result.report,
            )
            if completed_job is None:
                raise RuntimeError(
                    f"Collection job {job_id} is not running and cannot be completed."
                )

    return completed_job
