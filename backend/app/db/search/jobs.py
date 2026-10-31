"""Claim discovery jobs, reserve their online quota and recover or fail current attempts."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.execution.quotas import reserve_quota_limits
from app.db.execution.worker_claims import read_worker_claim, record_worker_claim
from app.db.schema import _require_current_schema
from app.db.serialization import _jsonb
from app.policies.quotas import (
    public_daily_quota,
)
from collector.diagnostics import Diagnostic


async def claim_search(*, claim_token: UUID | None = None):
    """Claim or recover discovery with one token; commit the task and receipt together."""
    claim_token = claim_token or uuid4()
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            receipt = await read_worker_claim(connection, claim_token, "search")
            if receipt is not None:
                return await _fetchone(
                    connection,
                    """SELECT * FROM search_sessions
                       WHERE id = %s AND status = 'running' AND updated_at = %s""",
                    (UUID(receipt["resource_id"]), receipt["claim_version"]),
                )
            row = await _fetchone(
                connection,
                """
                UPDATE search_sessions
                SET status = 'running', attempt_token = %s, updated_at = NOW()
                WHERE id = (SELECT id FROM search_sessions
                            WHERE status = 'queued' AND execution_mode = 'worker'
                            ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)
                    AND status = 'queued'
                RETURNING *
            """,
                (claim_token,),
            )
            if row is not None:
                await record_worker_claim(
                    connection, claim_token, "search", row["id"], row["updated_at"],
                )
    return row


async def _lock_attempt(connection, job):
    return await _fetchone(
        connection,
        """
        SELECT * FROM search_sessions WHERE id = %s AND owner_id = %s AND status = 'running'
            AND attempt_token = %s AND attempt_number = %s FOR UPDATE
    """,
        (job["id"], job["owner_id"], job["attempt_token"], job["attempt_number"]),
    )


async def reserve_external_search(job):
    """An acknowledged reservation survives a lost commit reply; no double charge."""
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            current = await _lock_attempt(connection, job)
            if current is None:
                return False
            if current["online_quota_attempt"] != current["attempt_number"]:
                if current["access_mode"] == "public":
                    await reserve_quota_limits(
                        connection, (public_daily_quota("online_daily"),), amount=1
                    )
                await connection.execute(
                    """
                    UPDATE search_sessions SET online_quota_attempt = attempt_number WHERE id = %s
                """,
                    (job["id"],),
                )
            return True


async def fail_discovery(job, *, origin, error, diagnostics, retry_at=None):
    """Record discovery failure only for the matching owner, attempt number and token."""
    async with _require_database_pool().connection() as connection:
        return await _fetchone(
            connection,
            """
            UPDATE search_sessions SET status = 'error', origin = %s, error = %s, errors = %s,
                discovery_complete = FALSE, retry_at = %s, attempt_token = NULL,
                updated_at = NOW(), finished_at = NOW()
            WHERE id = %s AND owner_id = %s AND status = 'running'
                AND attempt_token = %s AND attempt_number = %s RETURNING id
        """,
            (
                origin,
                error,
                _jsonb(diagnostics),
                retry_at,
                job["id"],
                job["owner_id"],
                job["attempt_token"],
                job["attempt_number"],
            ),
        )


async def mark_interrupted_search_sessions_error() -> int:
    """Close searches abandoned by a previous single application process."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _fetchall(
            connection,
            """
            UPDATE search_sessions
            SET status = 'error',
                error = 'Search interrupted by application restart.',
                errors = %s, discovery_complete = FALSE, attempt_token = NULL,
                updated_at = NOW(),
                finished_at = NOW()
            WHERE status = 'running'
            RETURNING id
            """,
            (_jsonb([Diagnostic("processing_interrupted", "search").to_dict()]),),
        )
        return len(rows)
