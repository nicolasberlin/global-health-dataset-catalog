from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from collector.storage.models import (
    CollectedDataset,
    DistributionCandidate,
    ValidationResult,
)

from .connection import Row, _fetchall, _fetchone, _require_database_pool
from .schema import _require_current_schema
from .serialization import (
    _deserialize_geography,
    _deserialize_signals,
    _format_optional_timestamp,
    _format_timestamp,
    _serialize_geography,
    _serialize_signals,
)


async def save_collected_datasets(
    source_url: str,
    datasets: list[CollectedDataset],
    collection_job_id: int | None = None,
) -> list[CollectedDataset]:
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


async def list_collected_datasets() -> list[CollectedDataset]:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        dataset_rows = await _fetchall(
            connection,
            """
            SELECT id, source_url, dataset_url, title, description, publisher,
                   hosting_platform, uploader, geography, discovery_method,
                   dataset_signals, health_signals, first_seen_at, last_seen_at,
                   updated_at
            FROM collected_datasets
            ORDER BY updated_at DESC, title
            """,
        )
        distribution_rows = await _fetchall(
            connection,
            """
            SELECT *
            FROM collected_distributions
            ORDER BY probability DESC, url
            """,
        )

    distributions_by_dataset_id: dict[int, list[Row]] = {}
    for row in distribution_rows:
        distributions_by_dataset_id.setdefault(int(row["dataset_id"]), []).append(row)

    return [
        _collected_dataset_from_rows(
            dataset_row,
            distributions_by_dataset_id.get(int(dataset_row["id"]), []),
        )
        for dataset_row in dataset_rows
    ]


async def list_dataset_discovery_observations(
    dataset_id: int | None = None,
) -> list[dict[str, int | str | None]]:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _select_dataset_discovery_observations(connection, dataset_id)

    return [_dataset_discovery_observation_to_dict(row) for row in rows]


async def _save_collected_dataset(
    connection: AsyncConnection[DictRow],
    source_url: str,
    dataset: CollectedDataset,
    collection_job_id: int | None,
) -> CollectedDataset:
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
    row = await _fetchone(
        connection,
        """
        INSERT INTO collected_datasets (
            source_url, dataset_url, title, description, publisher,
            hosting_platform, uploader, geography, discovery_method,
            dataset_signals, health_signals, first_seen_at, last_seen_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
        )
        ON CONFLICT(dataset_url) DO UPDATE SET
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
            health_signals = excluded.health_signals,
            last_seen_at = NOW(),
            updated_at = NOW()
        RETURNING id, source_url, dataset_url, title, description, publisher,
                  hosting_platform, uploader, geography, discovery_method,
                  dataset_signals, health_signals, first_seen_at, last_seen_at,
                  updated_at
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
            _serialize_signals(dataset.health_signals),
        ),
    )
    if row is None:
        raise RuntimeError("Collected dataset upsert did not return a row.")
    return row


async def _insert_dataset_discovery_observation(
    connection: AsyncConnection[DictRow],
    dataset_id: int,
    source_url: str,
    discovery_method: str,
    collection_job_id: int | None,
) -> None:
    await connection.execute(
        """
        INSERT INTO dataset_discovery_observations (
            collection_job_id, dataset_id, source_url, discovery_method, observed_at
        )
        VALUES (%s, %s, %s, %s, NOW())
        """,
        (collection_job_id, dataset_id, source_url, discovery_method),
    )


async def _select_dataset_discovery_observations(
    connection: AsyncConnection[DictRow],
    dataset_id: int | None,
) -> list[Row]:
    sql = """
        SELECT observation.id, observation.dataset_id, dataset.dataset_url,
               observation.collection_job_id,
               observation.source_url, observation.discovery_method,
               observation.observed_at
        FROM dataset_discovery_observations AS observation
        JOIN collected_datasets AS dataset ON dataset.id = observation.dataset_id
    """
    parameters: tuple[int, ...] = ()
    if dataset_id is not None:
        sql += " WHERE observation.dataset_id = %s"
        parameters = (dataset_id,)
    sql += " ORDER BY observation.observed_at DESC, observation.id DESC"

    return await _fetchall(connection, sql, parameters)


def _dataset_discovery_observation_to_dict(
    row: Row,
) -> dict[str, int | str | None]:
    return {
        "id": int(row["id"]),
        "dataset_id": int(row["dataset_id"]),
        "dataset_url": str(row["dataset_url"]),
        "collection_job_id": (
            int(row["collection_job_id"])
            if row["collection_job_id"] is not None
            else None
        ),
        "source_url": str(row["source_url"]),
        "discovery_method": str(row["discovery_method"]),
        "observed_at": _format_timestamp(row["observed_at"]),
    }


def _validation_results_by_distribution_key(
    validation_results: list[ValidationResult],
) -> dict[tuple[str, str], ValidationResult]:
    validation_by_distribution_key: dict[tuple[str, str], ValidationResult] = {}
    for validation in validation_results:
        key = (validation.url, validation.format)
        if key in validation_by_distribution_key:
            raise ValueError(
                "Duplicate validation result for distribution "
                f"url={validation.url!r}, format={validation.format!r}."
            )
        validation_by_distribution_key[key] = validation

    return validation_by_distribution_key


def _orphan_validation_result_error(
    dataset: CollectedDataset,
    validation_keys: set[tuple[str, str]],
) -> ValueError | None:
    distribution_keys = {
        (distribution.url, distribution.format) for distribution in dataset.distributions
    }
    orphan_validation_keys = sorted(validation_keys - distribution_keys)
    if not orphan_validation_keys:
        return None

    formatted_keys = ", ".join(
        f"url={url!r}, format={format_!r}" for url, format_ in orphan_validation_keys
    )
    return ValueError(
        "Validation result does not match any distribution for dataset "
        f"{dataset.dataset_url!r}: {formatted_keys}."
    )


async def _upsert_collected_distributions(
    connection: AsyncConnection[DictRow],
    dataset_id: int,
    dataset: CollectedDataset,
) -> None:
    validation_by_distribution_key = _validation_results_by_distribution_key(
        dataset.validation_results
    )
    orphan_error = _orphan_validation_result_error(
        dataset,
        set(validation_by_distribution_key),
    )
    if orphan_error is not None:
        raise orphan_error

    for distribution in dataset.distributions:
        await _upsert_collected_distribution(
            connection,
            dataset_id,
            distribution,
            validation_by_distribution_key.get((distribution.url, distribution.format)),
        )


async def _upsert_collected_distribution(
    connection: AsyncConnection[DictRow],
    dataset_id: int,
    distribution: DistributionCandidate,
    validation: ValidationResult | None,
) -> None:
    # validation_attempted means the distribution has been checked at least once.
    # Crawls that see the distribution without revalidating it preserve the last
    # validation result and its last_checked_at timestamp.
    validation_attempted = validation is not None
    await connection.execute(
        """
        INSERT INTO collected_distributions (
            dataset_id, url, format, probability, anchor, extension, mime_type,
            nearby_text, same_domain, dom_path, signals, first_seen_at, last_seen_at,
            last_checked_at, validation_attempted, validation_final_url, validation_ok,
            validation_http_status, validation_mime_type, validation_size_bytes,
            validation_etag, validation_last_modified, validation_content_disposition,
            validation_error
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            NOW(),
            NOW(),
            CASE WHEN %s THEN NOW() ELSE NULL END,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT(dataset_id, url, format) DO UPDATE SET
            probability = excluded.probability,
            anchor = excluded.anchor,
            extension = excluded.extension,
            mime_type = excluded.mime_type,
            nearby_text = excluded.nearby_text,
            same_domain = excluded.same_domain,
            dom_path = excluded.dom_path,
            signals = excluded.signals,
            last_seen_at = NOW(),
            last_checked_at = CASE
                WHEN excluded.validation_attempted THEN NOW()
                ELSE collected_distributions.last_checked_at
            END,
            validation_attempted = CASE
                WHEN excluded.validation_attempted THEN TRUE
                ELSE collected_distributions.validation_attempted
            END,
            validation_final_url = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_final_url
                ELSE collected_distributions.validation_final_url
            END,
            validation_ok = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_ok
                ELSE collected_distributions.validation_ok
            END,
            validation_http_status = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_http_status
                ELSE collected_distributions.validation_http_status
            END,
            validation_mime_type = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_mime_type
                ELSE collected_distributions.validation_mime_type
            END,
            validation_size_bytes = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_size_bytes
                ELSE collected_distributions.validation_size_bytes
            END,
            validation_etag = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_etag
                ELSE collected_distributions.validation_etag
            END,
            validation_last_modified = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_last_modified
                ELSE collected_distributions.validation_last_modified
            END,
            validation_content_disposition = CASE
                WHEN excluded.validation_attempted
                    THEN excluded.validation_content_disposition
                ELSE collected_distributions.validation_content_disposition
            END,
            validation_error = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_error
                ELSE collected_distributions.validation_error
            END
        """,
        (
            dataset_id,
            distribution.url,
            distribution.format,
            distribution.probability,
            distribution.anchor,
            distribution.extension,
            distribution.mime_type,
            distribution.nearby_text,
            distribution.same_domain,
            distribution.dom_path,
            _serialize_signals(distribution.signals),
            validation_attempted,
            validation_attempted,
            validation.final_url if validation else "",
            validation.ok if validation else False,
            validation.http_status if validation else None,
            validation.mime_type if validation else "",
            validation.size_bytes if validation else None,
            validation.etag if validation else "",
            validation.last_modified if validation else "",
            validation.content_disposition if validation else "",
            validation.error if validation else "",
        ),
    )


async def _fetch_collected_distribution_rows(
    connection: AsyncConnection[DictRow],
    dataset_id: int,
) -> list[Row]:
    return await _fetchall(
        connection,
        """
        SELECT *
        FROM collected_distributions
        WHERE dataset_id = %s
        ORDER BY probability DESC, url
        """,
        (dataset_id,),
    )


def _collected_dataset_from_rows(
    dataset_row: Row,
    distribution_rows: list[Row],
) -> CollectedDataset:
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
        )
        for row in distribution_rows
        if bool(row["validation_attempted"])
    ]

    return CollectedDataset(
        dataset_url=str(dataset_row["dataset_url"]),
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
        health_signals=_deserialize_signals(
            dataset_row["health_signals"],
            "collected_datasets.health_signals",
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
