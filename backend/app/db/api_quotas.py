"""PostgreSQL quotas and work admission; counters commit with the work they admit."""

from __future__ import annotations

from dataclasses import dataclass

from app.quota_policy import QuotaExceeded, QuotaLimit, QuotaUnavailable, WorkAdmission

from .connection import _fetchone, _require_database_pool
from .schema import _require_current_schema


@dataclass(frozen=True)
class APIQuotaDecision:
    """Result of reserving quota units in a fixed UTC window."""

    allowed: bool
    request_count: int
    retry_after_seconds: int


async def consume_api_quota(owner_id: str, operation: str, *, limit: int) -> APIQuotaDecision:
    """Consume one request from an owner's minute quota."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        return await _consume_quota(connection, QuotaLimit(owner_id, operation, limit), amount=1)


async def consume_quota_limits(quotas: tuple[QuotaLimit, ...]) -> None:
    """Charge all request limits or none, before any external request is started."""

    try:
        async with _require_database_pool().connection() as connection:
            await _require_current_schema(connection)
            async with connection.transaction():
                await reserve_quota_limits(connection, quotas, amount=1)
    except (QuotaExceeded, QuotaUnavailable):
        raise
    except Exception as exception:
        raise QuotaUnavailable() from exception


async def reserve_quota_limits(connection, quotas: tuple[QuotaLimit, ...], *, amount: int) -> None:
    """The caller must own a transaction; rejection must roll back its entire reservation."""

    if amount == 0:
        return
    for quota in sorted(quotas, key=lambda item: (item.owner_id, item.operation)):
        try:
            decision = await _consume_quota(connection, quota, amount=amount)
        except Exception as exception:
            raise QuotaUnavailable() from exception
        if not decision.allowed:
            raise QuotaExceeded(decision.retry_after_seconds)


async def lock_work_admission(connection, admission: WorkAdmission | None) -> None:
    if admission is not None:
        # Always acquire this before locking a candidate/job. No network calls run under it.
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('global-health-work-admission', 0))",
        )


async def reserve_work(connection, admission: WorkAdmission | None, *, amount: int) -> None:
    """Reserve one slot per candidate pipeline or explicit retry in the caller's transaction."""

    if admission is None or amount == 0:
        return
    if admission.max_active is not None:
        # One snapshot covers both queues: classification completion moves a slot between them.
        row = await _fetchone(connection, """
            SELECT (SELECT count(*) FROM repository_candidates
                    WHERE classification_status IN ('queued', 'classifying'))
                 + (SELECT count(*) FROM collection_jobs
                    WHERE status IN ('pending', 'running')) AS active
        """)
        if row["active"] + amount > admission.max_active:
            raise QuotaExceeded(5, "The processing queue is full. Please try again later.")
    await reserve_quota_limits(connection, admission.quotas, amount=amount)


async def _consume_quota(connection, quota: QuotaLimit, *, amount: int) -> APIQuotaDecision:
    owner_id, operation = quota.owner_id.strip(), quota.operation.strip()
    if not owner_id or not operation:
        raise ValueError("Quota owner ID and operation are required.")
    if quota.limit < 1 or amount < 1 or quota.window not in {"minute", "day"}:
        raise ValueError("Invalid quota limit, amount or window.")
    seconds = 60 if quota.window == "minute" else 86_400
    row = await _fetchone(connection, """
        WITH quota_window AS (
            SELECT date_trunc(%s, statement_timestamp() AT TIME ZONE 'UTC')
                   AT TIME ZONE 'UTC' AS started_at
        ), consumed AS (
            INSERT INTO api_rate_limits (owner_id, operation, window_started_at, request_count)
            SELECT %s, %s, started_at, %s FROM quota_window WHERE %s <= %s
            ON CONFLICT(owner_id, operation) DO UPDATE
            SET window_started_at = GREATEST(api_rate_limits.window_started_at,
                                            EXCLUDED.window_started_at),
                request_count = CASE
                    WHEN api_rate_limits.window_started_at < EXCLUDED.window_started_at
                    THEN EXCLUDED.request_count
                    ELSE api_rate_limits.request_count + EXCLUDED.request_count
                END,
                updated_at = statement_timestamp()
            WHERE api_rate_limits.window_started_at < EXCLUDED.window_started_at
               OR api_rate_limits.request_count + EXCLUDED.request_count <= %s
            RETURNING request_count, window_started_at
        )
        SELECT EXISTS(SELECT 1 FROM consumed) AS allowed,
            COALESCE((SELECT request_count FROM consumed),
                     (SELECT request_count FROM api_rate_limits
                      WHERE owner_id = %s AND operation = %s),
                     0) AS request_count,
            GREATEST(1, CEIL(EXTRACT(EPOCH FROM (
                COALESCE((SELECT window_started_at FROM consumed), quota_window.started_at)
                + %s * INTERVAL '1 second' - statement_timestamp()
            )))::INTEGER) AS retry_after_seconds
        FROM quota_window
    """, (quota.window, owner_id, operation, amount, amount, quota.limit, quota.limit,
          owner_id, operation, seconds))
    if row is None:
        raise RuntimeError("Quota consumption returned no result.")
    return APIQuotaDecision(bool(row["allowed"]), int(row["request_count"]),
                            int(row["retry_after_seconds"]))
