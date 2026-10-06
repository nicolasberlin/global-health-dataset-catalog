"""Requeue the existing work item without releasing its admitted capacity."""

from __future__ import annotations

from app.retry_policy import plan_retry

from .connection import _fetchone, _require_database_pool
from .serialization import _jsonb


async def schedule_llm_retry(item_id, version, diagnostics, *, collection=False):
    table = "collection_jobs" if collection else "repository_candidates"
    column = "status" if collection else "classification_status"
    running, queued = ("running", "pending") if collection else ("classifying", "queued")
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            row = await _fetchone(
                connection, f"SELECT * FROM {table} WHERE id = %s FOR UPDATE", (item_id,)
            )
            if row is None or row[column] != running or row["updated_at"] != version:
                return True, diagnostics  # Already committed or superseded.
            due, diagnostics = plan_retry(
                diagnostics,
                round_number=row["retry_round"],
                started_at=row["retry_started_at"] or row["updated_at"],
            )
            if due is None:
                return False, diagnostics
            extra = ", outcome = NULL, finished_at = NULL" if collection else ""
            await connection.execute(
                f"""
                UPDATE {table} SET {column} = %s, next_retry_at = %s,
                    retry_round = retry_round + 1, errors = %s, error = '', updated_at = NOW()
                    {extra} WHERE id = %s
            """,
                (queued, due, _jsonb([item.to_dict() for item in diagnostics]), item_id),
            )
            return True, diagnostics
