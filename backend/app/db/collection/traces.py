"""Guarded, owner-scoped observations; no result write occurs before final validation."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import uuid4

from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.public_history import HistoryPage, bounded_diagnostics, public_label, public_timestamp
from app.db.serialization import _jsonb
from collector.collection.contracts import public_url
from collector.collection.failures import FAILURE_PHASES

MAX_CHECKS_PER_METHOD = 100
MAX_CHECKS_PER_PAGE = 2000


def safe_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return ""
    try:
        if urlsplit(value).scheme not in {"http", "https"}:
            return ""
        return public_url(value)
    except ValueError:
        return ""


def safe_resource_key(value):
    if isinstance(value, str) and "://" in value:
        return safe_url(value)
    label = public_label(value, maximum=512)
    if label or not isinstance(value, str) or not value:
        return label
    # Keep stable correlation for filenames outside the public identifier grammar.
    return "resource:" + sha256(value.encode()).hexdigest()


def safe_coverage(value):
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


async def write_collection_trace(job_id, claim_version, sequence, observation):
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            job = await _fetchone(
                connection,
                "SELECT retry_cycle FROM collection_jobs "
                "WHERE id = %s AND status = 'running' AND updated_at = %s FOR UPDATE",
                (job_id, claim_version),
            )
            if job is None:
                return False
            row = await _fetchone(
                connection,
                """
                INSERT INTO collection_method_attempts
                    (id, job_id, claim_version, retry_cycle, sequence, observation)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(job_id, claim_version, sequence)
                DO UPDATE SET observation = EXCLUDED.observation RETURNING id
            """,
                (
                    uuid4(),
                    job_id,
                    claim_version,
                    job["retry_cycle"],
                    sequence,
                    _jsonb(safe_observation(observation)),
                ),
            )
            checks = observation.get("checks", [])
            for check in checks[:MAX_CHECKS_PER_METHOD] if isinstance(checks, list) else []:
                if not isinstance(check, dict):
                    continue
                clean = safe_check(check)
                key = safe_resource_key(check.get("resource_key"))
                if not key:
                    continue
                await connection.execute(
                    """
                    INSERT INTO collection_resource_checks(method_id, resource_key, observation)
                    VALUES (%s, %s, %s) ON CONFLICT(method_id, resource_key)
                    DO UPDATE SET observation = EXCLUDED.observation
                """,
                    (row["id"], key, _jsonb(clean)),
                )
            return True


async def read_collection_trace(job_id, owner_id, *, limit=100, offset=0):
    from app.db.classification.votes import read_collection_vote_history
    from app.db.collection.jobs import get_collection_job_for_owner

    page = HistoryPage(limit, offset)
    job = await get_collection_job_for_owner(job_id, owner_id)
    if job is None:
        return None
    async with _require_database_pool().connection() as connection:
        rows = await _fetchall(
            connection,
            """
            SELECT id, retry_cycle, sequence, observation FROM collection_method_attempts
            WHERE job_id = %s ORDER BY claim_version DESC, sequence DESC LIMIT %s OFFSET %s
        """,
            (job_id, page.limit + 1, page.offset),
        )
        truncated = len(rows) > page.limit
        rows = list(reversed(rows[: page.limit]))
        checks = await _fetchall(
            connection,
            """
            WITH ranked AS (
                SELECT r.method_id, r.resource_key, r.observation,
                    row_number() OVER (PARTITION BY method_id ORDER BY resource_key) AS position,
                    count(*) OVER (PARTITION BY method_id) AS total
                FROM collection_resource_checks r WHERE r.method_id = ANY(%s::uuid[])
            )
            SELECT method_id, resource_key, observation, total FROM ranked
            WHERE position <= %s ORDER BY method_id, resource_key LIMIT %s
        """,
            ([row["id"] for row in rows], MAX_CHECKS_PER_METHOD, MAX_CHECKS_PER_PAGE + 1),
        )
    by_method = defaultdict(list)
    totals = {}
    for check in checks[:MAX_CHECKS_PER_PAGE]:
        method_id = check["method_id"]
        totals[method_id] = check["total"]
        by_method[method_id].append(
            {
                "resource_key": safe_resource_key(check["resource_key"]),
                **safe_check(check["observation"]),
            }
        )
    return {
        "job_id": job_id,
        **page.metadata(truncated),
        "checks_truncated": len(checks) > MAX_CHECKS_PER_PAGE
        or any(count > MAX_CHECKS_PER_METHOD for count in totals.values()),
        "classification_history": await read_collection_vote_history(job_id, owner_id),
        "coverage": safe_coverage(job.get("coverage", {})),
        "method_attempts": [
            {
                "id": str(r["id"]),
                "retry_cycle": r["retry_cycle"],
                "sequence": r["sequence"],
                **safe_observation(r["observation"]),
                "checks": by_method[r["id"]],
            }
            for r in rows
        ],
    }
