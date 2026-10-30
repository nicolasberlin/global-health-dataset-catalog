"""Persist distribution evidence and its matching validation without opening transactions."""

from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.connection import Row, _fetchall
from app.db.serialization import _serialize_signals
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult


def _validation_results_by_distribution_key(
    validation_results: list[ValidationResult],
) -> dict[tuple[str, str], ValidationResult]:
    """Index validations by URL and format, rejecting duplicate evidence."""

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
    """Describe validation evidence that has no matching distribution."""

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
    """Validate evidence links and upsert each currently observed distribution.

    Existing distributions absent from the new observation are retained; this
    function does not interpret absence from one crawl as deletion.
    """

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
    """Deduplicate a distribution by dataset, URL, and format.

    Discovery evidence and ``last_seen_at`` are refreshed on conflict.
    Validation fields and ``last_checked_at`` change only when the current save
    supplies a matching validation result, preserving the last known check
    otherwise.
    """

    validation_attempted = validation is not None
    await connection.execute(
        """
        INSERT INTO collected_distributions (
            dataset_id, url, format, probability, anchor, extension, mime_type,
            nearby_text, same_domain, dom_path, signals, first_seen_at, last_seen_at,
            last_checked_at, validation_attempted, validation_final_url, validation_ok,
            validation_http_status, validation_mime_type, validation_size_bytes,
            validation_etag, validation_last_modified, validation_content_disposition,
            validation_error, validation_status, validation_reason
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            NOW(),
            NOW(),
            CASE WHEN %s THEN NOW() ELSE NULL END,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
            END,
            validation_status = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_status
                ELSE collected_distributions.validation_status
            END,
            validation_reason = CASE
                WHEN excluded.validation_attempted THEN excluded.validation_reason
                ELSE collected_distributions.validation_reason
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
            validation.status if validation else "unconfirmed",
            validation.reason if validation else "",
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
