"""Group actual worker claims, rather than merging retries sharing the same job."""

from __future__ import annotations

import hashlib


def group_attempts(trace, claims):
    groups = []
    for collection in trace.get("collections", []):
        if not collection:
            continue
        by_claim = {}
        for method in collection.get("method_attempts", []):
            claim = claims.get(method.get("id"))
            # Missing legacy claim evidence must not merge separate sequence-0 runs.
            key = claim or f"unknown:{method.get('id', len(by_claim))}"
            if key not in by_claim:
                identity = f"{collection['job_id']}:{key}"
                by_claim[key] = {
                    "case_id": "attempt-" + hashlib.sha256(identity.encode()).hexdigest()[:20],
                    "job_id": collection["job_id"],
                    "claim_version": claim,
                    "retry_cycle": method.get("retry_cycle"),
                    "methods": [],
                    "collector_version": None,
                }
            by_claim[key]["methods"].append(method)
        ordered = list(by_claim.values())
        ordered.sort(
            key=lambda group: group["claim_version"] or group["methods"][0].get("started_at", "")
        )
        previous = None
        for group in ordered:
            group["methods"].sort(key=lambda method: method.get("sequence", 0))
            group["previous_case_id"] = previous
            group["previous_case_scope"] = "available history; earlier attempts may be missing"
            previous = group["case_id"]
            checks = [check for method in group["methods"] for check in method.get("checks", [])]
            group["checks_recorded"] = len(checks)
            group["available_checks"] = sum(check.get("status") == "available" for check in checks)
            group["history_truncated"] = collection.get("history_truncated", False)
            groups.append(group)
    return groups
