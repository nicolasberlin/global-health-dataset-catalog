"""Explicit retention maintenance; dry-run by default, never invoked by startup."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass

from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.schema import validate_database_schema


@dataclass(frozen=True)
class RetentionPolicy:
    quota_days: int | None = 8
    trace_days: int | None = 90
    vote_history_days: int | None = 90
    search_days: int | None = None
    command_days: int | None = None
    worker_claim_days: int | None = None
    idempotency_window_days: int | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value is not None and (type(value) is not int or not 1 <= value <= 36_500):
                raise ValueError(f"{name} must be between 1 and 36500 days, or unset.")
        if self.command_days is not None and (
            self.idempotency_window_days is None or self.command_days < self.idempotency_window_days
        ):
            raise ValueError(
                "Command pruning requires an explicit idempotency window no longer "
                "than command retention. Command receipts otherwise remain unlimited."
            )
        if self.search_days is not None and self.command_days is not None:
            if self.search_days < self.command_days:
                raise ValueError("Search retention must cover the command retention window.")


# These predicates also protect persisted queued/running work while the API is stopped.
# Applying retention owns the same singleton lock as the API, so a terminal item
# cannot be requeued between checking its status and deleting its old history.
_TERMINAL_CANDIDATE = """
    EXISTS (SELECT 1 FROM repository_candidates c WHERE c.id = r.repository_candidate_id
        AND c.classification_status IN ('accepted', 'rejected', 'error')
        AND NOT EXISTS (SELECT 1 FROM collection_job_candidates a
            JOIN collection_jobs j ON j.id = a.job_id
            WHERE a.candidate_id = c.id AND j.status IN ('pending', 'running')))
"""
_TERMINAL_COLLECTION = """
    EXISTS (SELECT 1 FROM collection_jobs j WHERE j.id = r.collection_job_id
        AND j.status IN ('done', 'error')
        AND NOT EXISTS (SELECT 1 FROM collection_jobs child
            WHERE COALESCE(child.classification_root_id, child.id) = j.id
              AND child.status IN ('pending', 'running')))
"""


def _retention_operations(policy: RetentionPolicy):
    """Return only fixed SQL identifiers; no SQL fragments originate in configuration."""
    yield (
        "quota_counters",
        "api_rate_limits",
        policy.quota_days,
        """
        item.updated_at < statement_timestamp() - %s * INTERVAL '1 day'
    """,
    )
    yield (
        "collection_traces",
        "collection_method_attempts",
        policy.trace_days,
        """
        item.created_at < statement_timestamp() - %s * INTERVAL '1 day'
        AND EXISTS (SELECT 1 FROM collection_jobs j WHERE j.id = item.job_id
                    AND j.status IN ('done', 'error'))
    """,
    )
    yield (
        "vote_history",
        "classification_vote_attempts",
        policy.vote_history_days,
        f"""
        item.finished_at < statement_timestamp() - %s * INTERVAL '1 day'
        AND item.status <> 'running'
        AND EXISTS (SELECT 1 FROM classification_runs r WHERE r.id = item.run_id
                    AND ({_TERMINAL_CANDIDATE} OR {_TERMINAL_COLLECTION}))
    """,
    )
    yield (
        "worker_receipts",
        "worker_claims",
        policy.worker_claim_days,
        """
        item.claim_version < statement_timestamp() - %s * INTERVAL '1 day'
        AND (
            (item.queue = 'search' AND EXISTS (SELECT 1 FROM search_sessions s
                WHERE s.id::text = item.resource_id
                  AND s.status IN ('completed', 'partial', 'error')))
            OR (item.queue = 'classification' AND EXISTS (SELECT 1 FROM repository_candidates c
                WHERE c.id::text = item.resource_id
                  AND c.classification_status IN ('accepted', 'rejected', 'error')
                  AND NOT EXISTS (SELECT 1 FROM collection_job_candidates a
                    JOIN collection_jobs j ON j.id = a.job_id
                    WHERE a.candidate_id = c.id AND j.status IN ('pending', 'running'))))
            OR (item.queue = 'collection' AND EXISTS (SELECT 1 FROM collection_jobs j
                WHERE j.id::text = item.resource_id AND j.status IN ('done', 'error')))
        )
    """,
    )
    yield (
        "command_receipts",
        "api_commands",
        policy.command_days,
        """
        item.created_at < statement_timestamp() - %s * INTERVAL '1 day'
        AND (
            (item.operation IN ('search_create', 'search_retry')
                AND EXISTS (SELECT 1 FROM search_sessions s
                    WHERE s.id::text = item.result->>'search_id'
                      AND s.status IN ('completed', 'partial', 'error')
                      AND NOT EXISTS (SELECT 1 FROM repository_candidates c
                        WHERE c.search_session_id = s.id
                          AND c.classification_status IN ('queued', 'classifying'))
                      AND NOT EXISTS (SELECT 1 FROM repository_candidates c
                        JOIN collection_job_candidates a ON a.candidate_id = c.id
                        JOIN collection_jobs j ON j.id = a.job_id
                        WHERE c.search_session_id = s.id AND j.status IN ('pending', 'running'))))
            OR (item.operation = 'classification'
                AND EXISTS (SELECT 1 FROM repository_candidates c
                    WHERE c.id::text = item.result->>'candidate_id'
                      AND c.classification_status IN ('accepted', 'rejected', 'error')
                      AND NOT EXISTS (SELECT 1 FROM collection_job_candidates a
                        JOIN collection_jobs j ON j.id = a.job_id
                        WHERE a.candidate_id = c.id AND j.status IN ('pending', 'running'))))
            OR (item.operation = 'collection_retry'
                AND EXISTS (SELECT 1 FROM collection_jobs j
                    WHERE j.id::text = item.result->>'job_id' AND j.status IN ('done', 'error')))
        )
    """,
    )
    # Retained receipts keep their targets resolvable, including indefinite defaults.
    # Jobs referenced by the original candidate use RESTRICT; exclude them rather
    # than dropping lineage, ownership or shared-catalog provenance.
    yield (
        "search_history",
        "search_sessions",
        policy.search_days,
        """
        item.updated_at < statement_timestamp() - %s * INTERVAL '1 day'
        AND item.status IN ('completed', 'partial', 'error')
        AND NOT EXISTS (SELECT 1 FROM repository_candidates c
            WHERE c.search_session_id = item.id
              AND c.classification_status IN ('queued', 'classifying'))
        AND NOT EXISTS (SELECT 1 FROM repository_candidates c
            JOIN classification_runs r ON r.repository_candidate_id = c.id
            WHERE c.search_session_id = item.id)
        AND NOT EXISTS (SELECT 1 FROM repository_candidates c
            JOIN collection_job_candidates a ON a.candidate_id = c.id
            JOIN collection_jobs j ON j.id = a.job_id
            WHERE c.search_session_id = item.id AND j.status IN ('pending', 'running'))
        AND NOT EXISTS (SELECT 1 FROM collection_jobs j JOIN repository_candidates c
            ON c.id = j.repository_candidate_id WHERE c.search_session_id = item.id)
        AND NOT EXISTS (SELECT 1 FROM api_commands command WHERE
            command.result->>'search_id' = item.id::text
            OR EXISTS (SELECT 1 FROM repository_candidates c WHERE c.search_session_id = item.id
                AND command.result->>'candidate_id' = c.id::text))
        AND NOT EXISTS (SELECT 1 FROM worker_claims claim WHERE
            (claim.queue = 'search' AND claim.resource_id = item.id::text)
            OR EXISTS (SELECT 1 FROM repository_candidates c WHERE c.search_session_id = item.id
                AND claim.queue = 'classification' AND claim.resource_id = c.id::text))
    """,
    )


async def maintain_database(
    policy: RetentionPolicy | None = None,
    *,
    apply: bool = False,
    batch_size: int = 1000,
) -> dict:
    """Report eligible rows; an explicit apply prunes bounded batches under exclusive ownership.

    Dataset records, distributions, current votes and vote-run snapshots are never
    deleted. Historical attempts do not determine cached vote validity.
    """
    policy = policy or RetentionPolicy()
    if type(apply) is not bool or type(batch_size) is not int or not 1 <= batch_size <= 10_000:
        raise ValueError("Apply must be boolean and batch size must be between 1 and 10000.")
    await validate_database_schema()
    report = {
        "dry_run": not apply,
        "policy": asdict(policy),
        "batch_size": batch_size,
        "tables": {},
    }
    async with AsyncExitStack() as stack:
        ownership = None
        if apply:
            from app.db.execution.application_lock import application_lock

            ownership = await stack.enter_async_context(application_lock())
        async with _require_database_pool().connection() as connection:
            async with connection.transaction():
                if not apply:
                    await connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                await connection.execute("SET LOCAL statement_timeout = '5s'")
                await connection.execute("SET LOCAL lock_timeout = '1s'")
                for name, table, days, predicate in _retention_operations(policy):
                    if days is None:
                        report["tables"][name] = {
                            "retention_days": None,
                            "eligible": 0,
                            "deleted": 0,
                        }
                        continue
                    row = await _fetchone(
                        connection,
                        f"SELECT count(*) AS count FROM {table} item WHERE {predicate}",
                        (days,),
                    )
                    deleted = []
                    if apply:
                        deleted = await _fetchall(
                            connection,
                            f"""
                            WITH selected AS (
                                SELECT item.ctid FROM {table} item WHERE {predicate}
                                ORDER BY item.ctid LIMIT %s FOR UPDATE SKIP LOCKED
                            )
                            DELETE FROM {table} target USING selected
                            WHERE target.ctid = selected.ctid RETURNING 1
                        """,
                            (days, batch_size),
                        )
                    report["tables"][name] = {
                        "retention_days": days,
                        "eligible": int(row["count"]),
                        "deleted": len(deleted),
                    }
                if ownership is not None:
                    await ownership.check()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after stopping the API; default is dry-run."
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    for name, default in asdict(RetentionPolicy()).items():
        parser.add_argument("--" + name.replace("_", "-"), type=int, default=default)
    arguments = vars(parser.parse_args())
    apply, batch_size = arguments.pop("apply"), arguments.pop("batch_size")
    try:
        policy = RetentionPolicy(**arguments)
    except ValueError as exception:
        parser.error(str(exception))

    async def run():
        from app.db.connection import close_database_pool, open_database_pool

        await open_database_pool()
        try:
            result = await maintain_database(policy, apply=apply, batch_size=batch_size)
            print(json.dumps(result, sort_keys=True, indent=2))
        finally:
            await close_database_pool()

    try:
        asyncio.run(run())
    except Exception as exception:
        # Connection/library errors can contain credentials or provider text.
        # The local command uses the same non-disclosing failure policy as HTTP.
        category = (
            "application_already_running"
            if type(exception).__name__ == "ApplicationAlreadyRunning"
            else "database_maintenance_failed"
        )
        print(
            json.dumps(
                {
                    "error": category,
                    "message": (
                        "Maintenance could not complete. "
                        "Check database access, schema and API ownership."
                    ),
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
