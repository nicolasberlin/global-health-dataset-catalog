from dataclasses import replace

import pytest
from app.db.connection import _fetchone, _require_database_pool
from app.routes.collector import _collector_validation

from collector.classification.page import PageClassification
from collector.discovery.adapters import DiscoveredPage
from collector.main import collect_source_with_report
from collector.repository_search import RepositorySearchResult
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    HTTPProbe,
    ValidationResult,
)
from collector.validation.downloads import validate_distribution

pytestmark = pytest.mark.anyio
URL = "https://example.org/data.csv"


def dataset(validation):
    return CollectedDataset(
        dataset_url="https://example.org/dataset", title="Health", description="",
        publisher="", hosting_platform="", uploader="", dataset_signals={},
        distributions=[DistributionCandidate(URL, "CSV", .9)],
        validation_results=[validation],
    )


@pytest.mark.parametrize("body,expected_format", [
    (b"country\tvalue\nCH\t1\n", "TSV"),
    (b'{"data":[{"country":"CH"}]}', "JSON"),
])
async def test_sampled_format_stays_consistent_through_collection_and_storage(
    database, body, expected_format,
):
    class Classifier:
        def classify(self, page, distributions):
            return PageClassification(accepted=True)

    result = collect_source_with_report(
        "https://example.org", classifier=Classifier(),
        discover=lambda _: [DiscoveredPage(
            url="https://example.org/dataset", title="Health", discovery_method="test",
            distributions=(DistributionCandidate(URL, "CSV", .9),),
        )],
        validate=lambda item: validate_distribution(
            item, probe=lambda url, method, **kw: HTTPProbe(
                url, url, 200, {"content-type": "text/csv"}, body if method == "GET" else b"",
            ),
        ),
    )
    assert len(result.datasets) == 1
    await database.init_database()
    await database.save_collected_datasets("https://example.org", result.datasets)
    stored = (await database.list_collected_datasets())[0]
    assert stored.distributions[0].format == expected_format
    assert stored.validation_results[0].format == expected_format
    assert stored.validation_results[0].ok


@pytest.mark.parametrize("fmt", ["CSV", "ZIP"])
async def test_plain_errors_at_download_urls_stay_unconfirmed_in_saved_audit(database, fmt):
    url = f"https://example.org/data.{fmt.lower()}"
    validation = validate_distribution(
        DistributionCandidate(url, fmt, .9),
        probe=lambda url, method, **kw: HTTPProbe(
            url, url, 200, {}, b"Service unavailable" if method == "GET" else b"",
        ),
    )
    assert validation.status == "unconfirmed"
    await database.init_database()
    job = await database.create_collection_job("https://example.org")
    await database.mark_collection_job_running(job["id"])
    await database.complete_collection_job(job["id"], CollectionResult(
        report=CollectionReport(invalid_distribution_count=1, validation_failures=[validation]),
    ))
    async with _require_database_pool().connection() as connection:
        row = await _fetchone(connection,
                             "SELECT validation_failures FROM collection_jobs WHERE id = %s",
                             (job["id"],))
    failure = row["validation_failures"][0]
    assert failure["format"] == fmt
    assert failure["status"] == "unconfirmed"
    assert failure["ok"] is False
    assert failure["reason"] == validation.reason
    assert await database.list_collected_datasets() == []


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


@pytest.mark.parametrize("code,body,status", [
    (401, b"", "restricted"),
    (403, b"", "unconfirmed"),
    (403, b"<html>Authentication required</html>", "restricted"),
    (200, b'<html><form><input type="password"></form></html>', "restricted"),
    (200, b"<html>CAPTCHA</html>", "unconfirmed"),
])
async def test_access_diagnosis_survives_storage_and_public_conversion(
    database, code, body, status,
):
    await database.init_database()
    validation = validate_distribution(
        DistributionCandidate(URL, "CSV", .9),
        probe=lambda url, method, **kw: HTTPProbe(
            url, url, code, {"content-type": "text/html"}, body if method == "GET" else b"",
        ),
    )
    # Exercise serialization independently of the collector's publication filter.
    await database.save_collected_datasets(URL, [dataset(validation)])
    stored = (await database.list_collected_datasets())[0].validation_results[0]
    public = _collector_validation(stored)
    assert stored.status == public.status == validation.status == status
    assert stored.reason == public.reason == validation.reason
    assert stored.ok is public.ok is False

    job = await database.create_collection_job(URL)
    await database.mark_collection_job_running(job["id"])
    await database.complete_collection_job(job["id"], CollectionResult(
        report=CollectionReport(invalid_distribution_count=1, validation_failures=[validation]),
    ))
    async with _require_database_pool().connection() as connection:
        row = await _fetchone(connection,
                             "SELECT validation_failures FROM collection_jobs WHERE id = %s",
                             (job["id"],))
    failure = row["validation_failures"][0]
    assert failure["status"] == public.status
    assert failure["reason"] == public.reason
    assert failure["ok"] is False


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
            ALTER TABLE search_sessions DROP COLUMN errors,
                DROP COLUMN local_result_count, DROP COLUMN discovery_complete;
            ALTER TABLE repository_candidates DROP COLUMN errors;
            ALTER TABLE collection_jobs DROP COLUMN errors, DROP COLUMN outcome;
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
