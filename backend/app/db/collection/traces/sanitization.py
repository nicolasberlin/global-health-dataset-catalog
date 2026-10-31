"""Filter stored and public trace evidence without database or network operations."""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit

from app.db.public_history import bounded_diagnostics, public_label, public_timestamp
from collector.collection.contracts import public_url
from collector.collection.failures import FAILURE_PHASES

# Apply the same evidence bound when recording and exposing resource checks.
MAX_CHECKS_PER_METHOD = 100


def safe_url(value):
    """Keep a bounded public HTTP URL, removing credentials and sensitive query values."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return ""
    try:
        if urlsplit(value).scheme not in {"http", "https"}:
            return ""
        return public_url(value)
    except ValueError:
        return ""


def safe_resource_key(value):
    """Retain a public resource label or a stable digest for an unpublishable filename."""
    if isinstance(value, str) and "://" in value:
        return safe_url(value)
    label = public_label(value, maximum=512)
    if label or not isinstance(value, str) or not value:
        return label
    # Keep stable correlation for filenames outside the public identifier grammar.
    return "resource:" + sha256(value.encode()).hexdigest()


def safe_coverage(value):
    """Keep only recognized coverage fields and bounded integer counters."""
    if not isinstance(value, dict):
        return {}
    clean = {}
    for field in ("max_saved", "max_checks", "discovered", "checked", "validated"):
        count = value.get(field)
        if type(count) is int and 0 <= count <= 1_000_000:
            clean[field] = count
    if type(value.get("limited")) is bool:
        clean["limited"] = value["limited"]
    if value.get("policy") == "bounded_validated_resources":
        clean["policy"] = value["policy"]
    if isinstance(value.get("discovery"), str) and value["discovery"] in {"listed", "unknown"}:
        clean["discovery"] = value["discovery"]
    return clean


def safe_check(value):
    """Expose recognized access evidence and controlled diagnostic codes only."""
    if not isinstance(value, dict):
        return {}
    clean = {"url": safe_url(value.get("url"))}
    format_ = public_label(value.get("format"), maximum=50)
    if format_:
        clean["format"] = format_
    status = value.get("status")
    if isinstance(status, str) and status in {
        "available",
        "restricted",
        "unavailable",
        "unconfirmed",
    }:
        clean["status"] = status
    http_status = value.get("http_status")
    if type(http_status) is int and 100 <= http_status <= 599:
        clean["http_status"] = http_status
    if value.get("code"):
        clean["code"] = bounded_diagnostics([{"code": value["code"]}], stage="validation")[0][
            "code"
        ]
    return clean


def safe_observation(observation):
    """Filter method observations and reconstruct messages from controlled diagnostic codes."""
    if not isinstance(observation, dict):
        return {}
    clean = {}
    method = public_label(observation.get("method"), maximum=100)
    if method:
        clean["method"] = method
    for field in ("started_at", "finished_at"):
        timestamp = public_timestamp(observation.get(field))
        if timestamp:
            clean[field] = timestamp
    for field, allowed in (
        (
            "status",
            {"running", "succeeded", "failed", "empty", "rejected", "inconclusive", "blocked"},
        ),
        ("discovery_coverage", {"listed", "unknown"}),
    ):
        value = observation.get(field)
        if isinstance(value, str) and value in allowed:
            clean[field] = value
    count = observation.get("resource_count")
    if type(count) is int and 0 <= count <= 1_000_000:
        clean["resource_count"] = count
    count = observation.get("request_attempts")
    if type(count) is int and 1 <= count <= 60:
        clean["request_attempts"] = count
    if (
        isinstance(observation.get("failure_phase"), str)
        and observation["failure_phase"] in FAILURE_PHASES
    ):
        clean["failure_phase"] = observation["failure_phase"]
    # Reconstruct messages from controlled codes; never persist provider exception text.
    if observation.get("code"):
        diagnostic = bounded_diagnostics([{"code": observation["code"]}], stage="collection")[0]
        clean["code"], clean["reason"] = diagnostic["code"], diagnostic["message"]
    for key in ("http_status", "service_http_status", "metadata_http_status"):
        status = observation.get(key)
        if type(status) is int and 100 <= status <= 599:
            clean[key] = status
    metadata_code = observation.get("metadata_code")
    if isinstance(metadata_code, str) and metadata_code in {
        "repository_http_error",
        "repository_network_error",
        "repository_invalid_json",
        "repository_response_too_large",
        "repository_metadata_invalid",
    }:
        clean["metadata_code"] = metadata_code
    for k in ("requested_url", "final_url"):
        clean[k] = safe_url(observation.get(k))
    return clean
