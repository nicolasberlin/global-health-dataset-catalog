"""Prepare stored collector data for API responses.

search_progress.load_search_progress() calls public_search_progress() for snapshots;
catalog.read_collected_by_id() calls public_collected_dataset() for full datasets.
The smaller helpers prepare nested candidates, classifications and collections.
These functions transform data already in memory; they perform no database or
network calls and never start processing. FastAPI serializes the returned models
as JSON. Here, 'public' means suitable for a client, in both local and public mode;
raw internal failure details remain in storage and server logs.
"""

from __future__ import annotations

from typing import Any

from app.api.schemas import (
    CollectorAutomaticCollection,
    CollectorCollectedDataset,
    CollectorCollectionJob,
    CollectorDistribution,
    CollectorRepositoryClassification,
    CollectorRepositorySearchItem,
    CollectorSearchProgressResponse,
    CollectorValidation,
)
from app.db.collection.jobs import CollectionJobReservation
from app.db.collection.traces import safe_coverage, safe_observation
from app.search.summary import summarize_search
from collector.diagnostics import Diagnostic, public_diagnostics
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult


def public_collection_job(job: dict[str, Any]) -> CollectorCollectionJob:
    """Select public fields and derive messages without copying internal errors."""

    status = job["status"]
    saved_count = job["saved_count"]
    messages = {
        "pending": "Collection pending.",
        "running": "Collection in progress.",
        "done": (
            f"{saved_count} dataset(s) saved."
            if saved_count
            else "Collection completed without saved datasets."
        ),
        "error": "Collection failed.",
    }
    outcome = (job.get("outcome") or "incomplete") if status in {"done", "error"} else None
    errors = public_diagnostics(job.get("errors", []))
    if outcome == "incomplete" and not errors:
        errors = [Diagnostic("legacy_unknown", "collection").to_dict()]
    if status == "done" and outcome == "incomplete":
        messages["done"] = f"Collection incomplete; {saved_count} dataset(s) saved."
    return CollectorCollectionJob(
        execution_status=(
            "waiting_retry"
            if status == "pending" and any(item["recovery"] == "automatic" for item in errors)
            else {"pending": "queued", "running": "running", "done": "finished", "error": "failed"}[
                status
            ]
        ),
        outcome=outcome,
        errors=errors,
        id=job["id"],
        source_url=job["source_url"],
        kind=job.get("kind", "source"),
        status=status,
        saved_count=saved_count,
        classification_progress=job.get("classification_progress", {}),
        dataset_ids=job.get("dataset_ids", []),
        discovered_count=job.get("discovered_count", 0),
        analyzed_count=job.get("analyzed_count", 0),
        accepted_count=job.get("accepted_count", 0),
        rejected_count=job.get("rejected_count", 0),
        invalid_distribution_count=job.get("invalid_distribution_count", 0),
        discovery_methods=job.get("discovery_methods", []),
        method_attempts=[
            safe_observation(item)
            for item in (
                job.get("method_attempts", [])[:100]
                if isinstance(job.get("method_attempts"), list)
                else []
            )
        ],
        coverage=safe_coverage(job.get("coverage", {})),
        message=messages[status],
        error="Collection failed." if status == "error" else "",
        error_code="collection_failed" if status == "error" else "",
        created_at=job.get("created_at", ""),
        updated_at=job.get("updated_at", ""),
        finished_at=job.get("finished_at", ""),
    )


def _public_ensemble(ensemble: dict[str, Any]) -> dict[str, Any]:
    """Preserve decisions and votes while replacing technical failure details."""

    if "failures" not in ensemble:
        return dict(ensemble)
    return {
        **ensemble,
        "failures": [
            {
                "voter_id": failure["voter_id"],
                "error": "Classifier vote failed.",
                "error_code": "classifier_vote_failed",
                "errors": public_diagnostics(
                    failure.get("errors")
                    or [
                        Diagnostic(
                            "legacy_unknown", "classification", voter_id=failure["voter_id"]
                        ).to_dict(),
                    ]
                ),
            }
            for failure in ensemble["failures"]
        ],
    }


def public_repository_classification(
    classification: dict[str, Any] | None,
) -> CollectorRepositoryClassification | None:
    """Prepare a candidate's saved classification, filtering internal vote failures."""
    if classification is None:
        return None
    return CollectorRepositoryClassification(
        **{**classification, "ensemble": _public_ensemble(classification["ensemble"])},
    )


def public_dataset_signals(signals: dict[str, Any]) -> dict[str, Any]:
    """Copy a dataset's classification signals with client-safe model failures."""
    if "ensemble" not in signals:
        return dict(signals)
    return {**signals, "ensemble": _public_ensemble(signals["ensemble"])}


def _automatic_collection(
    collection: CollectionJobReservation | None,
) -> CollectorAutomaticCollection:
    """Present existing follow-up; this function never reserves or schedules work."""

    if collection is not None and collection.already_collected:
        return CollectorAutomaticCollection(
            state="saved",
            dataset_ids=list(collection.dataset_ids),
            execution_status="finished",
            outcome="results",
        )
    if collection is None or collection.job is None:
        # Legacy acceptances without follow-up are visible; reading cannot repair
        # them by silently creating new work.
        return CollectorAutomaticCollection(
            state="error",
            execution_status="failed",
            outcome="incomplete",
            errors=[Diagnostic("collection_not_scheduled", "collection").to_dict()],
            error="No collection is associated with this candidate.",
            error_code="collection_not_scheduled",
        )
    job = public_collection_job(collection.job)
    state = ("saved" if job.saved_count else "empty") if job.status == "done" else job.status
    return CollectorAutomaticCollection(
        state=state,
        job=job,
        dataset_ids=job.dataset_ids,
        execution_status=job.execution_status,
        outcome=job.outcome,
        errors=job.errors,
    )


def _collector_distribution(distribution: DistributionCandidate) -> CollectorDistribution:
    """Prepare one saved download link without requesting the remote resource."""
    return CollectorDistribution(
        url=distribution.url,
        format=distribution.format,
        probability=distribution.probability,
        anchor=distribution.anchor,
        mime_type=distribution.mime_type,
        first_seen_at=distribution.first_seen_at,
        last_seen_at=distribution.last_seen_at,
        last_checked_at=distribution.last_checked_at,
    )


def _collector_repository_candidate(
    candidate: dict[str, object],
    *,
    automatic_collection: CollectorAutomaticCollection | None = None,
) -> CollectorRepositorySearchItem:
    """Combine a saved candidate, its classification and its existing collection view."""
    return CollectorRepositorySearchItem(
        candidate_id=candidate["id"],
        search_id=candidate["search_session_id"],
        title=candidate["title"],
        description=candidate["description"],
        url=candidate["url"],
        source=candidate["source"],
        publisher=candidate["publisher"],
        date=candidate["publication_date"],
        doi=candidate["doi"],
        keywords=candidate["keywords"],
        metadata=candidate["metadata"],
        classification_status=candidate["classification_status"],
        classification_progress=candidate.get("classification_progress", {}),
        classification=public_repository_classification(candidate["classification"]),
        errors=public_diagnostics(
            candidate.get("errors")
            or (
                [Diagnostic("legacy_unknown", "classification").to_dict()]
                if candidate["classification_status"] == "error"
                else []
            )
        ),
        classification_error=(
            "Candidate classification failed."
            if candidate["classification_status"] == "error"
            else ""
        ),
        classification_error_code=(
            "classification_failed" if candidate["classification_status"] == "error" else ""
        ),
        automatic_collection=automatic_collection,
        created_at=candidate["created_at"],
        updated_at=candidate["updated_at"],
    )


def _collector_validation(validation: ValidationResult) -> CollectorValidation:
    """Present an existing resource check with a controlled failure message."""
    return CollectorValidation(
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


def public_collected_dataset(dataset: CollectedDataset) -> CollectorCollectedDataset:
    """Prepare a full dataset response for catalogue reads.

    Include its saved metadata, download links and validation results. The route
    has already loaded the dataset; this function only builds the response model.
    """
    return CollectorCollectedDataset(
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
        dataset_signals=public_dataset_signals(dataset.dataset_signals),
        distributions=[
            _collector_distribution(distribution) for distribution in dataset.distributions
        ],
        validation_results=[
            _collector_validation(validation) for validation in dataset.validation_results
        ],
        first_seen_at=dataset.first_seen_at,
        last_seen_at=dataset.last_seen_at,
        updated_at=dataset.updated_at,
    )


def public_search_progress(search_id, snapshot) -> CollectorSearchProgressResponse:
    """Convert read_search_progress() data into a client-facing progress response.

    snapshot contains the search row, its candidates and their collections. Build
    their response views, summarize processing status and gather saved dataset IDs.
    The client uses polling_required to decide whether to request another update.
    """

    search, candidates, collections = snapshot
    items = [
        _collector_repository_candidate(
            candidate,
            automatic_collection=(
                _automatic_collection(collections.get(candidate["id"]))
                if candidate["classification_status"] == "accepted"
                else None
            ),
        )
        for candidate in candidates
    ]
    summary = summarize_search(search, [item.model_dump() for item in items])
    summary["errors"] = public_diagnostics(summary["errors"])
    ids = list(
        dict.fromkeys(
            [
                *search.get("local_dataset_ids", []),
                *(
                    dataset_id
                    for item in items
                    if item.automatic_collection is not None
                    for dataset_id in item.automatic_collection.dataset_ids
                ),
            ]
        )
    )
    return CollectorSearchProgressResponse(
        search_id=search_id,
        items=items,
        query=search.get("query", ""),
        origin=search["origin"] if search["status"] not in {"queued", "running"} else None,
        local_dataset_ids=search.get("local_dataset_ids", []),
        dataset_ids=ids,
        warnings=search.get("warnings", []),
        attempt=search.get("attempt_number", 1),
        created_at=str(search.get("created_at", "")),
        updated_at=str(search.get("updated_at", "")),
        **summary,
    )
