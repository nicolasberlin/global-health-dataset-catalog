"""Read owner-scoped collection traces and filter legacy observations for publication."""

from __future__ import annotations

from collections import defaultdict

from app.db.classification.voting.history import read_collection_vote_history
from app.db.collection.job_reads import get_collection_job_for_owner
from app.db.collection.traces.sanitization import (
    MAX_CHECKS_PER_METHOD,
    safe_check,
    safe_coverage,
    safe_observation,
    safe_resource_key,
)
from app.db.connection import _fetchall, _require_database_pool
from app.db.public_history import HistoryPage

MAX_CHECKS_PER_PAGE = 2000


async def read_collection_trace(job_id, owner_id, *, limit=100, offset=0):
    """Read an owned trace with bounded paging and filter stored evidence for publication."""
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
