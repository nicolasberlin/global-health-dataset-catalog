from __future__ import annotations


def candidates(snapshot):
    result = {}
    items = snapshot["observation"]["trace"]["summary"].get("items", [])
    for item in items:
        job = (item.get("automatic_collection") or {}).get("job") or {}
        result[item["url"]] = {
            "title": item["title"],
            "classification": item.get("classification_status"),
            "job_id": job.get("id"),
            "outcome": job.get("outcome"),
            "saved_count": job.get("saved_count"),
            "coverage": job.get("coverage", {}),
            "errors": list(
                dict.fromkeys(
                    error["code"] for error in [*item.get("errors", []), *job.get("errors", [])]
                )
            ),
        }
    return result


def compare(left, right):
    if left.get("scope") != "candidate" or right.get("scope") != "candidate":
        raise ValueError(
            "Choose two candidate snapshots. "
            "Older whole-search evidence remains available for download."
        )
    if left["candidate"]["url"] != right["candidate"]["url"]:
        raise ValueError("Choose two snapshots of the same candidate URL.")
    before, after = candidates(left), candidates(right)
    return {
        "before": {key: left[key] for key in ("id", "captured_at", "collector_version")},
        "after": {key: right[key] for key in ("id", "captured_at", "collector_version")},
        "warnings": [
            "This compares captured observations, not proof of a causal improvement.",
            "Collector versions and complete historical parameters are not recorded by the source.",
            "An absent candidate is not evidence of rejection; search scope may differ.",
        ],
        "items": [
            {"url": url, "before": before.get(url), "after": after.get(url)}
            for url in sorted(set(before) | set(after))
        ],
    }
