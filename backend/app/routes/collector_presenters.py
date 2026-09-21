"""Public collector views. Internal diagnostics remain in storage and server logs."""

from __future__ import annotations

from typing import Any

from app.routes.collector_schemas import (
    CollectorCollectionJob,
    CollectorRepositoryClassification,
)


def public_collection_job(job: dict[str, Any]) -> CollectorCollectionJob:
    """Select public fields and derive messages without copying internal errors."""

    status = job["status"]
    saved_count = job["saved_count"]
    messages = {
        "pending": "Collection pending.",
        "running": "Collection in progress.",
        "done": (
            f"{saved_count} dataset(s) saved."
            if saved_count else "Collection completed without saved datasets."
        ),
        "error": "Collection failed.",
    }
    return CollectorCollectionJob(
        id=job["id"],
        source_url=job["source_url"],
        kind=job.get("kind", "source"),
        status=status,
        saved_count=saved_count,
        dataset_ids=job.get("dataset_ids", []),
        discovered_count=job.get("discovered_count", 0),
        analyzed_count=job.get("analyzed_count", 0),
        accepted_count=job.get("accepted_count", 0),
        rejected_count=job.get("rejected_count", 0),
        invalid_distribution_count=job.get("invalid_distribution_count", 0),
        discovery_methods=job.get("discovery_methods", []),
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
            }
            for failure in ensemble["failures"]
        ],
    }


def public_repository_classification(
    classification: dict[str, Any] | None,
) -> CollectorRepositoryClassification | None:
    if classification is None:
        return None
    return CollectorRepositoryClassification(
        **{**classification, "ensemble": _public_ensemble(classification["ensemble"])},
    )


def public_dataset_signals(signals: dict[str, Any]) -> dict[str, Any]:
    if "ensemble" not in signals:
        return dict(signals)
    return {**signals, "ensemble": _public_ensemble(signals["ensemble"])}
