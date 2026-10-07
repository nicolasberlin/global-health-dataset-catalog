"""Durable discovery commands and fenced execution, under the single-process policy."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.quota_policy import (
    QuotaExceeded,
    classification_admission,
    public_daily_quota,
    search_command_quotas,
    search_queue_capacity,
)

from .api_quotas import lock_work_admission, reserve_quota_limits, reserve_work
from .commands import CommandConflict, read_command, record_command
from .connection import _fetchone, _require_database_pool
from .repository_candidates import _save_repository_candidates
from .schema import _require_current_schema
from .search_results import save_local_results
from .search_sessions import _complete_search_session, _normalized_owner_id
from .serialization import _jsonb
from .worker_claims import read_worker_claim, record_worker_claim


async def admit_search(
    owner_id: str,
    key: str,
    *,
    query: str = "",
    access_mode: str,
    client_key: str | None,
    retry_search_id: UUID | None = None,
):
    owner_id = _normalized_owner_id(owner_id)
    if access_mode not in {"local", "token", "public"}:
        raise ValueError("Unsupported access mode.")
    if (access_mode == "public") != (client_key is not None):
        raise ValueError("Public discovery requires its server-derived quota key.")
    query = query.strip()
    if retry_search_id is None and not query:
        raise ValueError("Search query is required.")
    operation = "search_retry" if retry_search_id is not None else "search_create"
    payload = (
        {"search_id": str(retry_search_id)} if retry_search_id is not None else {"query": query}
    )
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            receipt = await read_command(connection, owner_id, key, operation, payload)
            if receipt:
                row = await _fetchone(
                    connection,
                    "SELECT * FROM search_sessions WHERE id = %s AND owner_id = %s",
                    (UUID(receipt["search_id"]), owner_id),
                )
                return row, True
            # Separate discovery capacity: admission of downstream work remains atomic
            # with publication, and cannot count the same stage transition twice.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('search-admission', 0))"
            )
            if retry_search_id is not None:
                row = await _fetchone(
                    connection,
                    "SELECT * FROM search_sessions WHERE id = %s AND owner_id = %s FOR UPDATE",
                    (retry_search_id, owner_id),
                )
                if row is None:
                    return None, False
                if row["execution_mode"] != "worker":
                    raise CommandConflict("Only asynchronous searches support this retry command.")
                if row["status"] in {"queued", "running"}:
                    await record_command(
                        connection,
                        owner_id,
                        key,
                        operation,
                        payload,
                        {"search_id": str(row["id"]), "attempt": row["attempt_number"]},
                    )
                    return row, False
                published = await _fetchone(
                    connection,
                    """
                    SELECT EXISTS(SELECT 1 FROM repository_candidates WHERE search_session_id = %s)
                        OR EXISTS(SELECT 1 FROM search_local_results WHERE search_id = %s) AS value
                """,
                    (retry_search_id, retry_search_id),
                )
                if published["value"] or row["status"] not in {"error", "partial"}:
                    raise CommandConflict("Discovery is complete; retry individual failed tasks.")
                if row["status"] == "partial" and row["discovery_complete"] is not False:
                    raise CommandConflict("This search does not require a discovery retry.")
                if row["retry_at"] is not None:
                    remaining = (row["retry_at"] - datetime.now(timezone.utc)).total_seconds()
                    if remaining > 0:
                        raise QuotaExceeded(int(remaining) + 1, "Discovery retry is not due yet.")
            active = await _fetchone(
                connection,
                """
                SELECT count(*) AS count FROM search_sessions
                WHERE execution_mode = 'worker' AND status IN ('queued', 'running')
            """,
            )
            if active["count"] >= search_queue_capacity():
                raise QuotaExceeded(5, "The search queue is full. Please try again later.")
            await reserve_quota_limits(
                connection, search_command_quotas(owner_id, client_key), amount=1
            )
            if retry_search_id is None:
                row = await _fetchone(
                    connection,
                    """
                    INSERT INTO search_sessions
                        (id, owner_id, query, status, execution_mode, access_mode, client_key)
                    VALUES (%s, %s, %s, 'queued', 'worker', %s, %s) RETURNING *
                """,
                    (uuid4(), owner_id, query, access_mode, client_key),
                )
            else:
                row = await _fetchone(
                    connection,
                    """
                    UPDATE search_sessions SET status = 'queued',
                        attempt_number = attempt_number + 1,
                        attempt_token = NULL, error = '', errors = '[]'::jsonb,
                        warnings = '[]'::jsonb, retry_at = NULL, discovery_complete = NULL,
                        local_result_count = NULL, finished_at = NULL, updated_at = NOW(),
                        access_mode = %s, client_key = %s
                    WHERE id = %s RETURNING *
                """,
                    (access_mode, client_key, retry_search_id),
                )
            await record_command(
                connection,
                owner_id,
                key,
                operation,
                payload,
                {"search_id": str(row["id"]), "attempt": row["attempt_number"]},
            )
    return row, False


async def claim_search(*, claim_token: UUID | None = None):
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


async def complete_discovery(job, result):
    """Publish associations/candidates, quotas and discovery outcome as one transaction."""
    admission = classification_admission(job["owner_id"], job["client_key"])
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            if result.origin == "online":
                await lock_work_admission(connection, admission)
            if await _lock_attempt(connection, job) is None:
                return False
            if result.origin == "database":
                ids = [dataset.database_id for dataset in result.datasets]
                await save_local_results(connection, job["id"], ids)
            else:
                ids = []
                rows = await _save_repository_candidates(
                    connection, job["id"], job["owner_id"], result.candidates
                )
                await reserve_work(
                    connection,
                    admission,
                    amount=sum(row["classification_status"] == "pending" for row in rows),
                )
                await connection.execute(
                    """
                    UPDATE repository_candidates SET classification_status = 'queued',
                        updated_at = NOW() WHERE search_session_id = %s
                        AND classification_status = 'pending'
                """,
                    (job["id"],),
                )
            await _complete_search_session(
                connection,
                job["id"],
                job["owner_id"],
                origin=result.origin,
                status="partial" if result.warnings else "completed",
                local_result_count=len(ids),
                discovery_complete=result.complete,
                errors=result.diagnostics,
                warnings=result.warning_records,
            )
            return True


async def fail_discovery(job, *, origin, error, diagnostics, retry_at=None):
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
