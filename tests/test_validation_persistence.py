from dataclasses import replace

import pytest
from app.db.connection import _fetchone, _require_database_pool

from collector.repository_search import RepositorySearchResult
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    ValidationResult,
)

pytestmark = pytest.mark.anyio
URL = "https://example.org/data.csv"


def dataset(validation):
    return CollectedDataset(
        dataset_url="https://example.org/dataset", title="Health", description="",
        publisher="", hosting_platform="", uploader="", dataset_signals={},
        distributions=[DistributionCandidate(URL, "CSV", .9)],
        validation_results=[validation],
    )


async def test_validation_status_large_size_and_rejected_audit_are_persisted(database):
    await database.init_database()
    validation = ValidationResult(URL, URL, "CSV", True, 200, size_bytes=4_200_000_000,
                                  status="available", reason="Data sample confirmed.")
    await database.save_collected_datasets(URL, [dataset(validation)])
    stored = (await database.list_collected_datasets())[0].validation_results[0]
    assert stored == validation

    failure = replace(validation, status="restricted", reason="Authentication is required.")
    job = await database.create_collection_job("https://example.org/restricted")
    await database.mark_collection_job_running(job["id"])
    await database.complete_collection_job(job["id"], CollectionResult(
        report=CollectionReport(invalid_distribution_count=1, validation_failures=[failure]),
    ))
    async with _require_database_pool().connection() as connection:
        row = await _fetchone(connection,
                             "SELECT validation_failures FROM collection_jobs WHERE id = %s",
                             (job["id"],))
    assert row["validation_failures"][0]["status"] == "restricted"
    assert row["validation_failures"][0]["reason"] == failure.reason
    assert row["validation_failures"][0]["ok"] is False


async def test_version_four_upgrade_preserves_existing_validation(database):
    await database.init_database()
    validation = ValidationResult(URL, URL, "CSV", True, 200, size_bytes=123)
    await database.save_collected_datasets(URL, [dataset(validation)])
    async with _require_database_pool().connection() as connection:
        await connection.execute("""
            ALTER TABLE collected_distributions
                DROP COLUMN validation_status, DROP COLUMN validation_reason,
                ALTER COLUMN validation_size_bytes TYPE INTEGER;
            ALTER TABLE collection_jobs DROP COLUMN validation_failures;
            DROP TABLE classification_votes, classification_runs;
            ALTER TABLE repository_candidates DROP COLUMN classification_progress;
            ALTER TABLE collection_jobs DROP COLUMN classification_progress,
                DROP COLUMN classification_root_id;
            DELETE FROM schema_migrations WHERE version >= 5;
        """)
    await database.init_database()
    await database.init_database()
    stored = (await database.list_collected_datasets())[0].validation_results[0]
    assert stored.status == "available"
    assert stored.size_bytes == 123
    await database.save_collected_datasets(
        URL, [dataset(replace(validation, size_bytes=4_200_000_000))],
    )
    stored = (await database.list_collected_datasets())[0].validation_results[0]
    assert stored.size_bytes == 4_200_000_000


async def test_search_commits_classification_queue_without_browser_submission(database):
    await database.init_database()
    search = await database.create_search_session("health", "alice")
    candidates = [RepositorySearchResult(title="Health", url=URL, source="DataCite")]
    stored = await database.complete_search_session_with_repository_candidates(
        search["id"], "alice", candidates * 2, status="completed",
    )
    assert len(stored) == 1
    assert stored[0]["classification_status"] == "queued"
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    claimed = await database.claim_candidate_classification()
    assert claimed["id"] == stored[0]["id"]
    assert claimed["owner_id"] == "alice"
    assert await database.claim_candidate_classification() is None
