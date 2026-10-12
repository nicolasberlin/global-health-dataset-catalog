"""Guarded, owner-scoped observations; no result write occurs before final validation."""

from __future__ import annotations

from uuid import uuid4

from collector.collection.contracts import public_url
from collector.collection.failures import FAILURE_PHASES
from collector.diagnostics import Diagnostic

from .connection import _fetchall, _fetchone, _require_database_pool
from .serialization import _jsonb


def safe_observation(observation):
    fields = (
        "method",
        "started_at",
        "finished_at",
        "status",
        "code",
        "http_status",
        "resource_count",
        "discovery_coverage",
    )
    clean = {k: observation[k] for k in fields if k in observation}
    if observation.get("failure_phase") in FAILURE_PHASES:
        clean["failure_phase"] = observation["failure_phase"]
    # Reconstruct messages from controlled codes; never persist provider exception text.
    if clean.get("code"):
        clean["reason"] = Diagnostic(clean["code"], "collection").message
    for key in ("service_http_status", "metadata_http_status"):
        status = observation.get(key)
        if type(status) is int and 100 <= status <= 599:
            clean[key] = status
    metadata_code = observation.get("metadata_code")
    if metadata_code in {
        "repository_http_error", "repository_network_error", "repository_invalid_json",
        "repository_response_too_large", "repository_metadata_invalid",
    }:
        clean["metadata_code"] = metadata_code
    for k in ("requested_url", "final_url"):
        clean[k] = public_url(str(observation.get(k, "")))
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
            for check in observation.get("checks", [])[:100]:
                clean = {
                    k: check[k] for k in ("format", "status", "http_status", "code") if k in check
                }
                clean["url"] = public_url(check["url"])
                key = str(check["resource_key"])[:2048]
                if "://" in key:
                    key = public_url(key)
                await connection.execute(
                    """
                    INSERT INTO collection_resource_checks(method_id, resource_key, observation)
                    VALUES (%s, %s, %s) ON CONFLICT(method_id, resource_key)
                    DO UPDATE SET observation = EXCLUDED.observation
                """,
                    (row["id"], key, _jsonb(clean)),
                )
            return True


async def read_collection_trace(job_id, owner_id):
    from .classification_votes import read_collection_vote_history
    from .collection_jobs import get_collection_job_for_owner

    job = await get_collection_job_for_owner(job_id, owner_id)
    if job is None:
        return None
    async with _require_database_pool().connection() as connection:
        rows = await _fetchall(
            connection,
            """
            SELECT id, retry_cycle, sequence, observation FROM collection_method_attempts
            WHERE job_id = %s ORDER BY claim_version DESC, sequence DESC LIMIT 1001
        """,
            (job_id,),
        )
        truncated = len(rows) > 1000
        rows = list(reversed(rows[:1000]))
        checks = await _fetchall(
            connection,
            """
            SELECT r.method_id, r.resource_key, r.observation FROM collection_resource_checks r
            WHERE r.method_id = ANY(%s::uuid[])
            ORDER BY r.method_id, r.resource_key
        """,
            ([row["id"] for row in rows],),
        )
    return {
        "job_id": job_id,
        "history_truncated": truncated,
        "classification_history": await read_collection_vote_history(job_id, owner_id),
        "coverage": job.get("coverage", {}),
        "method_attempts": [
            {
                "id": str(r["id"]),
                "retry_cycle": r["retry_cycle"],
                "sequence": r["sequence"],
                **safe_observation(r["observation"]),
                "checks": [
                    {"resource_key": c["resource_key"], **c["observation"]}
                    for c in checks
                    if c["method_id"] == r["id"]
                ],
            }
            for r in rows
        ],
    }
