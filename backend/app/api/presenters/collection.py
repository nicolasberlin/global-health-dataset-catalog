"""Present saved collection jobs and candidate follow-ups without scheduling work."""

from __future__ import annotations

from typing import Any

from app.api.schemas.collection import CollectionFollowUpView, CollectionJobView
from app.db.collection.reservations import CollectionJobReservation
from app.db.collection.traces.sanitization import safe_coverage, safe_observation
from collector.diagnostics import Diagnostic, public_diagnostics


def build_collection_job_view(job: dict[str, Any]) -> CollectionJobView:
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
    return CollectionJobView(
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


def build_collection_follow_up_view(
    collection: CollectionJobReservation | None,
) -> CollectionFollowUpView:
    """Present existing follow-up; this function never reserves or schedules work."""

    if collection is not None and collection.already_collected:
        return CollectionFollowUpView(
            state="saved",
            dataset_ids=list(collection.dataset_ids),
            execution_status="finished",
            outcome="results",
        )
    if collection is None or collection.job is None:
        # Legacy acceptances without follow-up are visible; reading cannot repair
        # them by silently creating new work.
        return CollectionFollowUpView(
            state="error",
            execution_status="failed",
            outcome="incomplete",
            errors=[Diagnostic("collection_not_scheduled", "collection").to_dict()],
            error="No collection is associated with this candidate.",
            error_code="collection_not_scheduled",
        )
    job = build_collection_job_view(collection.job)
    state = ("saved" if job.saved_count else "empty") if job.status == "done" else job.status
    return CollectionFollowUpView(
        state=state,
        job=job,
        dataset_ids=job.dataset_ids,
        execution_status=job.execution_status,
        outcome=job.outcome,
        errors=job.errors,
    )
