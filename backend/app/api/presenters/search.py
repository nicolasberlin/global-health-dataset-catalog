"""Present search snapshots and derive their public execution state and conclusion.

These functions transform data already in memory. They never query the database,
contact providers or schedule work. Final response construction filters diagnostics
before exposing them to clients.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from app.api.presenters.classification import public_repository_classification
from app.api.presenters.collection import public_automatic_collection
from app.api.schemas.collection import CollectionFollowUpView
from app.api.schemas.search import RepositoryCandidateView, SearchProgressResponse
from collector.diagnostics import Diagnostic, ExecutionStatus, Outcome, Stage, public_diagnostics


class SearchSummary(TypedDict):
    """Derived public state; a final outcome is available once polling stops."""

    execution_status: ExecutionStatus
    outcome: Outcome | None
    active_stages: list[Stage]
    errors: list[dict[str, Any]]
    local_result_count: int | None
    polling_required: bool


def summarize_search(
    search: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
) -> SearchSummary:
    """Aggregate one consistent snapshot without changing it or scheduling work.

    ``search`` is a persisted search row with ``status`` and optional ``origin``,
    ``errors``, ``discovery_complete`` and ``local_result_count``. Each item has a
    ``classification_status`` and may include diagnostics and a presented
    ``automatic_collection`` with execution state, outcome and saved dataset IDs.

    Active, queued or scheduled work keeps polling alive and leaves the outcome
    unknown. Otherwise, usable datasets may coexist with an incomplete outcome.
    Diagnostics are aggregated here; the API presenter sanitizes them afterward.
    """
    active: set[Stage] = set()
    queued: set[Stage] = set()
    waiting: set[Stage] = set()
    execution: ExecutionStatus
    outcome: Outcome | None
    errors = list(search.get("errors", []))
    incomplete = search.get("discovery_complete") is not True
    result_count = search.get("local_result_count") or 0
    completed_branches = 0
    blocked_branches = 0
    if search["status"] == "queued":
        queued.add("search")
    elif search["status"] == "running":
        active.add("search")
    elif search["status"] == "error":
        if not errors:
            errors.append(Diagnostic("legacy_unknown", "search").to_dict())
    elif incomplete and not errors:
        errors.append(Diagnostic("legacy_unknown", "search").to_dict())
    # A missing historical count is unknown, even when no candidates are present.
    if (
        search["status"] in {"completed", "partial"}
        and search.get("origin") == "database"
        and search.get("local_result_count") is None
    ):
        incomplete = True
        if not errors:
            errors.append(Diagnostic("legacy_unknown", "search").to_dict())

    dataset_ids: set[int] = set()
    for item in items:
        status = item["classification_status"]
        errors.extend(item.get("errors", []))
        if status == "classifying":
            active.add("classification")
        elif status == "queued":
            if any(error.get("recovery") == "automatic" for error in item.get("errors", [])):
                waiting.add("classification")
            else:
                queued.add("classification")
        elif status in {"pending", "error"}:
            incomplete = True
            blocked_branches += int(status == "error")
            if not item.get("errors"):
                code = "classification_not_requested" if status == "pending" else "legacy_unknown"
                errors.append(Diagnostic(code, "classification").to_dict())
        elif status == "rejected":
            # A semantic rejection is a concluded check, not an operational failure.
            completed_branches += 1
        elif status == "accepted":
            collection = item.get("automatic_collection") or {}
            errors.extend(collection.get("errors", []))
            dataset_ids.update(collection.get("dataset_ids", []))
            execution = collection.get("execution_status", "failed")
            if execution == "running":
                active.add("collection")
            elif execution == "waiting_retry":
                waiting.add("collection")
            elif execution == "queued":
                queued.add("collection")
            else:
                incomplete |= collection.get("outcome") not in {"results", "empty"}
                if execution == "failed":
                    blocked_branches += 1
                else:
                    completed_branches += 1

    result_count += len(dataset_ids)
    # Remaining work takes precedence over failed branches: running > queued > retry.
    if active or queued or waiting:
        execution = "running" if active else "queued" if queued else "waiting_retry"
        outcome = None
    else:
        execution = (
            "failed"
            if (
                search["status"] == "error"
                or (blocked_branches and not completed_branches and not result_count)
            )
            else "finished"
        )
        outcome = (
            "incomplete"
            if incomplete or execution == "failed"
            else "results"
            if result_count
            else "empty"
        )
    return {
        "execution_status": execution,
        "outcome": outcome,
        "active_stages": sorted(active),
        "errors": errors,
        "local_result_count": search.get("local_result_count"),
        "polling_required": bool(active or queued or waiting),
    }


def _collector_repository_candidate(
    candidate: dict[str, object],
    *,
    automatic_collection: CollectionFollowUpView | None = None,
) -> RepositoryCandidateView:
    """Combine a saved candidate, its classification and its existing collection view."""
    return RepositoryCandidateView(
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


def public_search_progress(search_id, snapshot) -> SearchProgressResponse:
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
                public_automatic_collection(collections.get(candidate["id"]))
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
    return SearchProgressResponse(
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
