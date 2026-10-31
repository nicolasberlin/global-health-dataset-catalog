"""Publish search results and candidate queues inside their existing atomic transactions."""

from __future__ import annotations

from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.classification.candidates import (
    _repository_candidate_to_dict,
    _save_repository_candidates,
)
from app.db.connection import Row, _fetchone, _require_database_pool
from app.db.execution.quotas import lock_work_admission, reserve_work
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from app.db.search.jobs import _lock_attempt
from app.db.search.sessions import SearchOrigin, SearchStatus, _search_session_to_dict
from app.db.serialization import _jsonb
from app.policies.quotas import (
    WorkAdmission,
    classification_admission,
)
from collector.diagnostics import Diagnostic
from collector.repository_search.models import RepositorySearchResult


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


async def complete_search_session(
    search_id: UUID,
    owner_id: str,
    *,
    origin: SearchOrigin,
    status: SearchStatus = "completed",
    error: str = "",
    errors: list[dict] | None = None,
    local_result_count: int | None = None,
    discovery_complete: bool | None = None,
    warnings: list[dict] | None = None,
    local_dataset_ids: list[int] | None = None,
) -> dict[str, object]:
    """Move a running search to one terminal state without overwriting it."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            row = await _complete_search_session(
                connection,
                search_id,
                owner_id,
                origin=origin,
                status=status,
                error=error,
                errors=errors,
                local_result_count=local_result_count,
                discovery_complete=discovery_complete,
                warnings=warnings,
            )
            if row is not None and local_dataset_ids is not None:
                await save_local_results(connection, search_id, local_dataset_ids)

    if row is None:
        raise RuntimeError("Search session is missing or already completed.")
    return _search_session_to_dict(row)


async def _complete_search_session(
    connection: AsyncConnection[DictRow],
    search_id: UUID,
    owner_id: str,
    *,
    origin: SearchOrigin,
    status: SearchStatus,
    error: str = "",
    errors: list[dict] | None = None,
    local_result_count: int | None = None,
    discovery_complete: bool | None = None,
    warnings: list[dict] | None = None,
) -> Row | None:
    if origin not in {"database", "online"}:
        raise ValueError(f"Unsupported search origin: {origin!r}.")
    if status not in {"completed", "partial", "error"}:
        raise ValueError(f"Unsupported terminal search status: {status!r}.")

    normalized_error = error.strip()
    if status == "error" and not normalized_error:
        raise ValueError("An errored search session requires an error message.")
    if status != "error" and normalized_error:
        raise ValueError("Only an errored search session may contain an error.")

    return await _fetchone(
        connection,
        """
        UPDATE search_sessions
        SET origin = %s,
            status = %s,
            error = %s,
            errors = %s, local_result_count = %s, discovery_complete = %s,
            warnings = %s, attempt_token = NULL, retry_at = NULL,
            updated_at = NOW(),
            finished_at = NOW()
        WHERE id = %s AND owner_id = %s AND status = 'running'
        RETURNING id, query, origin, status, error, errors,
                  local_result_count, discovery_complete,
                  created_at, updated_at, finished_at
        """,
        (origin, status, normalized_error,
         _jsonb(errors or ([Diagnostic("processing_failed", "search").to_dict()]
                          if status == "error" else [])),
         local_result_count,
         discovery_complete if discovery_complete is not None else status == "completed",
         _jsonb(warnings or []), search_id, validate_owner_id(owner_id)),
    )


async def save_local_results(connection, search_id, dataset_ids):
    """Associate existing dataset IDs in their result order using the caller's transaction."""
    if len(set(dataset_ids)) != len(dataset_ids):
        raise ValueError("Local result identifiers must be unique.")
    for position, dataset_id in enumerate(dataset_ids):
        await connection.execute(
            """
            INSERT INTO search_local_results (search_id, dataset_id, position)
            VALUES (%s, %s, %s)
        """,
            (search_id, dataset_id, position),
        )


async def complete_search_session_with_repository_candidates(
    search_id: UUID,
    owner_id: str,
    candidates: list[RepositorySearchResult],
    *,
    status: SearchStatus,
    errors: list[dict] | None = None,
    discovery_complete: bool | None = None,
    warnings: list[dict] | None = None,
    admission: WorkAdmission | None = None,
) -> list[dict[str, object]]:
    """Persist and enqueue online candidates, then finish their search atomically."""

    if status not in {"completed", "partial"}:
        raise ValueError("An online candidate search must complete or be partial.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            await lock_work_admission(connection, admission)
            rows = await _save_repository_candidates(
                connection,
                search_id,
                owner_id,
                candidates,
            )
            await reserve_work(connection, admission, amount=sum(
                row["classification_status"] == "pending" for row in rows
            ))
            session_row = await _complete_search_session(
                connection,
                search_id,
                owner_id,
                origin="online",
                status=status,
                errors=errors,
                discovery_complete=discovery_complete,
                warnings=warnings,
            )
            if session_row is None:
                raise RuntimeError("Search session is missing or already completed.")
            await connection.execute(
                """UPDATE repository_candidates SET classification_status = 'queued',
                          updated_at = NOW()
                   WHERE search_session_id = %s AND classification_status = 'pending'""",
                (search_id,),
            )
            for row in rows:
                if row["classification_status"] == "pending":
                    row["classification_status"] = "queued"
    return [_repository_candidate_to_dict(row) for row in rows]
