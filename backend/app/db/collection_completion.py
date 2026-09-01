from __future__ import annotations

from collector.storage.models import CollectionResult

from .collected_datasets import _save_collected_dataset
from .collection_jobs import _lock_running_collection_job, _mark_collection_job_done
from .connection import _require_database_pool
from .schema import _require_current_schema


async def complete_collection_job(
    job_id: int,
    collection_result: CollectionResult,
) -> dict[str, object]:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            job = await _lock_running_collection_job(connection, job_id)
            if job is None:
                raise RuntimeError(
                    f"Collection job {job_id} is not running and cannot be completed."
                )

            source_url = str(job["source_url"])
            saved_datasets = [
                await _save_collected_dataset(
                    connection,
                    source_url,
                    dataset,
                    job_id,
                )
                for dataset in collection_result.datasets
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
