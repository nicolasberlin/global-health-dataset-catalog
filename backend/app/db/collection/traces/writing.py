"""Persist bounded observations under the current collection claim version."""

from __future__ import annotations

from uuid import uuid4

from app.db.collection.traces.sanitization import (
    MAX_CHECKS_PER_METHOD,
    safe_check,
    safe_observation,
    safe_resource_key,
)
from app.db.connection import _fetchone, _require_database_pool
from app.db.serialization import _jsonb


async def write_collection_trace(job_id, claim_version, sequence, observation):
    """Record bounded observations only while the collection claim is still current."""
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
