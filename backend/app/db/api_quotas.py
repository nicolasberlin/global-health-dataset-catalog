"""Atomic fixed-window API quotas stored in PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass

from .connection import _fetchone, _require_database_pool
from .schema import _require_current_schema


@dataclass(frozen=True)
class APIQuotaDecision:
    """Result of consuming one request from a principal's minute window."""

    allowed: bool
    request_count: int
    retry_after_seconds: int


async def consume_api_quota(
    owner_id: str,
    operation: str,
    *,
    limit: int,
) -> APIQuotaDecision:
    """Atomically consume one fixed-minute quota unit for an API principal."""

    normalized_owner_id = owner_id.strip()
    normalized_operation = operation.strip()
    if not normalized_owner_id:
        raise ValueError("Quota owner ID is required.")
    if not normalized_operation:
        raise ValueError("Quota operation is required.")
    if limit < 1:
        raise ValueError("Quota limit must be greater than zero.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            WITH quota_window AS (
                SELECT date_trunc('minute', statement_timestamp()) AS started_at
            ),
            consumed AS (
                INSERT INTO api_rate_limits (
                    owner_id, operation, window_started_at, request_count
                )
                SELECT %s, %s, started_at, 1
                FROM quota_window
                ON CONFLICT(owner_id, operation) DO UPDATE
                SET window_started_at = CASE
                        WHEN api_rate_limits.window_started_at < EXCLUDED.window_started_at
                        THEN EXCLUDED.window_started_at
                        ELSE api_rate_limits.window_started_at
                    END,
                    request_count = CASE
                        WHEN api_rate_limits.window_started_at < EXCLUDED.window_started_at
                        THEN 1
                        ELSE api_rate_limits.request_count + 1
                    END,
                    updated_at = statement_timestamp()
                WHERE api_rate_limits.window_started_at < EXCLUDED.window_started_at
                   OR api_rate_limits.request_count < %s
                RETURNING request_count, window_started_at
            )
            SELECT
                EXISTS(SELECT 1 FROM consumed) AS allowed,
                COALESCE(
                    (SELECT request_count FROM consumed),
                    (
                        SELECT request_count
                        FROM api_rate_limits, quota_window
                        WHERE owner_id = %s AND operation = %s
                    ),
                    0
                ) AS request_count,
                GREATEST(
                    1,
                    CEIL(EXTRACT(EPOCH FROM (
                        COALESCE(
                            (SELECT window_started_at FROM consumed),
                            quota_window.started_at
                        ) + INTERVAL '1 minute'
                        - statement_timestamp()
                    )))::INTEGER
                ) AS retry_after_seconds
            FROM quota_window
            """,
            (
                normalized_owner_id,
                normalized_operation,
                limit,
                normalized_owner_id,
                normalized_operation,
            ),
        )

    if row is None:
        raise RuntimeError("Quota consumption returned no result.")
    return APIQuotaDecision(
        allowed=bool(row["allowed"]),
        request_count=int(row["request_count"]),
        retry_after_seconds=int(row["retry_after_seconds"]),
    )
