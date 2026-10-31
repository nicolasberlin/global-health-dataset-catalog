"""Present saved datasets, download links and validation results for catalogue reads."""

from __future__ import annotations

from app.api.presenters.classification import prepare_public_dataset_signals
from app.api.schemas.catalog import (
    CatalogDatasetView,
    DatasetDistributionView,
    DistributionValidationView,
)
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult


def _build_dataset_distribution_view(
    distribution: DistributionCandidate,
) -> DatasetDistributionView:
    """Prepare one saved download link without requesting the remote resource."""
    return DatasetDistributionView(
        url=distribution.url,
        format=distribution.format,
        probability=distribution.probability,
        anchor=distribution.anchor,
        mime_type=distribution.mime_type,
        first_seen_at=distribution.first_seen_at,
        last_seen_at=distribution.last_seen_at,
        last_checked_at=distribution.last_checked_at,
    )


def _build_distribution_validation_view(validation: ValidationResult) -> DistributionValidationView:
    """Present an existing resource check with a controlled failure message."""
    return DistributionValidationView(
        url=validation.url,
        final_url=validation.final_url,
        format=validation.format,
        ok=validation.ok,
        status=validation.status,
        reason=validation.reason,
        http_status=validation.http_status,
        mime_type=validation.mime_type,
        size_bytes=validation.size_bytes,
        etag=validation.etag,
        last_modified=validation.last_modified,
        content_disposition=validation.content_disposition,
        error="Resource validation failed." if not validation.ok else "",
        error_code="validation_failed" if not validation.ok else "",
    )


def build_catalog_dataset_view(dataset: CollectedDataset) -> CatalogDatasetView:
    """Prepare a full dataset response for catalogue reads.

    Include its saved metadata, download links and validation results. The route
    has already loaded the dataset; this function only builds the response model.
    """
    return CatalogDatasetView(
        id=dataset.database_id,
        source_url=dataset.source_url,
        dataset_url=dataset.dataset_url,
        title=dataset.title,
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform=dataset.hosting_platform,
        uploader=dataset.uploader,
        geography=list(dataset.geography),
        date_of_publication=dataset.date_of_publication,
        sharing_license=dataset.sharing_license,
        doi=dataset.doi,
        metadata_provenance=dataset.metadata_provenance,
        record_identity=dataset.record_identity,
        discovery_method=dataset.discovery_method,
        dataset_signals=prepare_public_dataset_signals(dataset.dataset_signals),
        distributions=[
            _build_dataset_distribution_view(distribution) for distribution in dataset.distributions
        ],
        validation_results=[
            _build_distribution_validation_view(validation)
            for validation in dataset.validation_results
        ],
        first_seen_at=dataset.first_seen_at,
        last_seen_at=dataset.last_seen_at,
        updated_at=dataset.updated_at,
    )
