"""Persist and rehydrate collected datasets with their distribution evidence."""

from __future__ import annotations

from dataclasses import replace

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.catalog.distributions import (
    _fetch_collected_distribution_rows,
    _upsert_collected_distributions,
)
from app.db.catalog.observations import _insert_dataset_discovery_observation
from app.db.connection import Row, _fetchall, _fetchone, _require_database_pool
from app.db.schema import _require_current_schema
from app.db.serialization import (
    _deserialize_geography,
    _deserialize_signals,
    _format_optional_timestamp,
    _format_timestamp,
    _serialize_geography,
    _serialize_signals,
)
from collector.storage.metadata import METADATA_FIELDS, metadata_evidence
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult


async def save_collected_datasets(
    source_url: str,
    datasets: list[CollectedDataset],
    collection_job_id: int | None = None,
) -> list[CollectedDataset]:
    """Upsert a batch of datasets in one transaction without changing job state.

    Any dataset, observation, distribution, or validation error rolls back the
    complete batch and propagates to the caller.
    """

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            return [
                await _save_collected_dataset(
                    connection,
                    source_url,
                    dataset,
                    collection_job_id,
                )
                for dataset in datasets
            ]


async def get_collected_datasets(dataset_ids: list[int]) -> list[CollectedDataset]:
    """Resolve explicit public catalog IDs independently of catalog pagination."""
    if len(dataset_ids) > 100 or any(value < 1 for value in dataset_ids):
        raise ValueError("Expected at most 100 positive dataset IDs.")
    if not dataset_ids:
        return []
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _fetchall(
            connection, "SELECT * FROM collected_datasets WHERE id = ANY(%s) ORDER BY id DESC",
            (dataset_ids,),
        )
        return await _datasets_with_distributions(connection, rows)


async def _datasets_with_distributions(connection, dataset_rows) -> list[CollectedDataset]:
    ids = [int(row["id"]) for row in dataset_rows]
    if not ids:
        return []
    rows = await _fetchall(
        connection,
        """SELECT * FROM collected_distributions WHERE dataset_id = ANY(%s)
           ORDER BY probability DESC, url""",
        (ids,),
    )
    by_id: dict[int, list[Row]] = {}
    for row in rows:
        by_id.setdefault(int(row["dataset_id"]), []).append(row)
    return [_collected_dataset_from_rows(row, by_id.get(int(row["id"]), []))
            for row in dataset_rows]


async def _save_collected_dataset(
    connection: AsyncConnection[DictRow],
    source_url: str,
    dataset: CollectedDataset,
    collection_job_id: int | None,
) -> CollectedDataset:
    """Upsert one dataset aggregate using the caller's active transaction.

    Each save also appends a discovery observation and upserts current
    distributions before reloading the stored aggregate.
    """

    dataset = replace(dataset, metadata_provenance={
        **metadata_evidence(dataset, kind="collection", source_url=source_url),
        **dataset.metadata_provenance,
    })
    dataset_row = await _upsert_collected_dataset(connection, source_url, dataset)
    dataset_id = int(dataset_row["id"])
    await _insert_dataset_discovery_observation(
        connection,
        dataset_id,
        source_url,
        dataset.discovery_method,
        collection_job_id,
    )
    await _upsert_collected_distributions(connection, dataset_id, dataset)

    return _collected_dataset_from_rows(
        dataset_row,
        await _fetch_collected_distribution_rows(connection, dataset_id),
    )


async def _upsert_collected_dataset(
    connection: AsyncConnection[DictRow],
    source_url: str,
    dataset: CollectedDataset,
) -> Row:
    """Deduplicate by the normalized dataset URL and refresh non-empty metadata.

    On conflict, empty descriptive values preserve existing data, while source
    URL and classifier signals are replaced. ``first_seen_at`` is retained and
    the last-seen and update timestamps advance. Failure to return the stored
    row raises ``RuntimeError``.
    """

    metadata_updates = ", ".join(
        f"""{field} = CASE
            WHEN EXISTS (
                SELECT 1 FROM jsonb_array_elements(
                    COALESCE(excluded.metadata_provenance->'{field}', '[]'::jsonb)
                ) AS evidence
                WHERE evidence->>'value' = excluded.{field}
                  AND evidence->>'kind' IN ('page', 'adapter')
            ) THEN COALESCE(NULLIF(excluded.{field}, ''), collected_datasets.{field})
            ELSE COALESCE(NULLIF(collected_datasets.{field}, ''), excluded.{field}) END"""
        for field in METADATA_FIELDS
    )
    provenance_values = ", ".join(
        f"""'{field}', COALESCE((SELECT jsonb_agg(DISTINCT evidence)
            FROM jsonb_array_elements(
                COALESCE(collected_datasets.metadata_provenance->'{field}', '[]'::jsonb)
                || COALESCE(excluded.metadata_provenance->'{field}', '[]'::jsonb)
            ) AS evidence), '[]'::jsonb)"""
        for field in METADATA_FIELDS
    )
    row = await _fetchone(
        connection,
        f"""
        INSERT INTO collected_datasets (
            source_url, dataset_url, title, description, publisher,
            hosting_platform, uploader, geography, discovery_method,
            dataset_signals, date_of_publication, sharing_license, doi, metadata_provenance,
            record_identity,
            first_seen_at, last_seen_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
        )
        ON CONFLICT(dataset_url) DO UPDATE SET
            {metadata_updates},
            metadata_provenance = jsonb_build_object({provenance_values}),
            record_identity = collected_datasets.record_identity || (
                SELECT COALESCE(jsonb_object_agg(key, value), '{{}}'::jsonb)
                FROM jsonb_each(excluded.record_identity)
                WHERE value <> '\"\"'::jsonb
            ),
            source_url = excluded.source_url,
            title = COALESCE(NULLIF(excluded.title, ''), collected_datasets.title),
            description = COALESCE(
                NULLIF(excluded.description, ''),
                collected_datasets.description
            ),
            publisher = COALESCE(
                NULLIF(excluded.publisher, ''),
                collected_datasets.publisher
            ),
            hosting_platform = COALESCE(
                NULLIF(excluded.hosting_platform, ''),
                collected_datasets.hosting_platform
            ),
            uploader = COALESCE(
                NULLIF(excluded.uploader, ''),
                collected_datasets.uploader
            ),
            geography = CASE
                WHEN excluded.geography <> '[]'::jsonb
                    THEN excluded.geography
                ELSE collected_datasets.geography
            END,
            discovery_method = COALESCE(
                NULLIF(excluded.discovery_method, ''),
                collected_datasets.discovery_method
            ),
            dataset_signals = excluded.dataset_signals,
            last_seen_at = NOW(),
            updated_at = NOW()
        RETURNING id, source_url, dataset_url, title, description, publisher,
                  hosting_platform, uploader, geography, discovery_method,
                  dataset_signals, date_of_publication, sharing_license, doi, metadata_provenance,
                  record_identity,
                  first_seen_at, last_seen_at, updated_at
        """,
        (
            source_url,
            dataset.dataset_url,
            dataset.title,
            dataset.description,
            dataset.publisher,
            dataset.hosting_platform,
            dataset.uploader,
            _serialize_geography(dataset.geography),
            dataset.discovery_method,
            _serialize_signals(dataset.dataset_signals),
            dataset.date_of_publication, dataset.sharing_license, dataset.doi,
            _serialize_signals(dataset.metadata_provenance),
            _serialize_signals(dataset.record_identity),
        ),
    )
    if row is None:
        raise RuntimeError("Collected dataset upsert did not return a row.")
    return row


def _collected_dataset_from_rows(
    dataset_row: Row,
    distribution_rows: list[Row],
) -> CollectedDataset:
    """Rehydrate one dataset aggregate and only attempted validations."""

    distributions = [
        DistributionCandidate(
            url=str(row["url"]),
            format=str(row["format"]),
            probability=float(row["probability"]),
            anchor=str(row["anchor"]),
            extension=str(row["extension"]),
            mime_type=str(row["mime_type"]),
            nearby_text=str(row["nearby_text"]),
            same_domain=bool(row["same_domain"]),
            dom_path=str(row["dom_path"]),
            signals=_deserialize_signals(
                row["signals"],
                "collected_distributions.signals",
            ),
            first_seen_at=_format_timestamp(row["first_seen_at"]),
            last_seen_at=_format_timestamp(row["last_seen_at"]),
            last_checked_at=_format_optional_timestamp(row["last_checked_at"]),
        )
        for row in distribution_rows
    ]
    validation_results = [
        ValidationResult(
            url=str(row["url"]),
            final_url=str(row["validation_final_url"]),
            format=str(row["format"]),
            ok=bool(row["validation_ok"]),
            http_status=row["validation_http_status"],
            mime_type=str(row["validation_mime_type"]),
            size_bytes=row["validation_size_bytes"],
            etag=str(row["validation_etag"]),
            last_modified=str(row["validation_last_modified"]),
            content_disposition=str(row["validation_content_disposition"]),
            error=str(row["validation_error"]),
            status=str(row["validation_status"]),
            reason=str(row["validation_reason"]),
        )
        for row in distribution_rows
        if bool(row["validation_attempted"])
    ]

    return CollectedDataset(
        dataset_url=str(dataset_row["dataset_url"]),
        date_of_publication=str(dataset_row["date_of_publication"]),
        sharing_license=str(dataset_row["sharing_license"]),
        doi=str(dataset_row["doi"]),
        metadata_provenance=_deserialize_signals(
            dataset_row["metadata_provenance"], "collected_datasets.metadata_provenance",
        ),
        record_identity=_deserialize_signals(
            dataset_row["record_identity"], "collected_datasets.record_identity",
        ),
        title=str(dataset_row["title"]),
        description=str(dataset_row["description"]),
        publisher=str(dataset_row["publisher"]),
        hosting_platform=str(dataset_row["hosting_platform"]),
        uploader=str(dataset_row["uploader"]),
        geography=tuple(
            _deserialize_geography(dataset_row["geography"])
        ),
        dataset_signals=_deserialize_signals(
            dataset_row["dataset_signals"],
            "collected_datasets.dataset_signals",
        ),
        distributions=distributions,
        discovery_method=str(dataset_row["discovery_method"]),
        validation_results=validation_results,
        source_url=str(dataset_row["source_url"]),
        database_id=int(dataset_row["id"]),
        first_seen_at=_format_timestamp(dataset_row["first_seen_at"]),
        last_seen_at=_format_timestamp(dataset_row["last_seen_at"]),
        updated_at=_format_timestamp(dataset_row["updated_at"]),
    )
