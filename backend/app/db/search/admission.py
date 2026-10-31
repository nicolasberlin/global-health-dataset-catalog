"""Accept or replay owned search commands with atomic quotas and idempotency receipts."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.db.connection import _fetchone, _require_database_pool
from app.db.execution.commands import CommandConflict, read_command, record_command
from app.db.execution.quotas import reserve_quota_limits
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from app.policies.quotas import (
    QuotaExceeded,
    search_command_quotas,
    search_queue_capacity,
)


async def admit_search(
    owner_id: str,
    key: str,
    *,
    query: str = "",
    access_mode: str,
    client_key: str | None,
    retry_search_id: UUID | None = None,
):
    """Admit or replay one owned command; quotas, work and receipt commit together."""
    owner_id = validate_owner_id(owner_id)
    if access_mode not in {"local", "public"}:
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
