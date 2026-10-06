"""Derive a search's public execution and conclusion from one durable snapshot."""

from collector.diagnostics import Diagnostic


def summarize_search(search: dict, items: list[dict]) -> dict:
    active, queued, waiting = set(), set(), set()
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
    if (search["status"] in {"completed", "partial"}
            and search.get("origin") == "database" and search.get("local_result_count") is None):
        incomplete = True
        if not errors:
            errors.append(Diagnostic("legacy_unknown", "search").to_dict())

    dataset_ids = set()
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
