"""Persistence and terminal state transitions for repository search sessions."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from .connection import Row, _fetchall, _fetchone, _require_database_pool
from .schema import _require_current_schema
from .serialization import _format_optional_timestamp, _format_timestamp

SearchOrigin = Literal["database", "online"]
SearchStatus = Literal["completed", "partial", "error"]


async def create_search_session(query: str, owner_id: str) -> dict[str, object]:
    """Create the durable record that owns one local-then-online search."""

    normalized_query = query.strip()
    normalized_owner_id = _normalized_owner_id(owner_id)
    if not normalized_query:
        raise ValueError("Search query is required.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            INSERT INTO search_sessions (id, owner_id, query)
            VALUES (%s, %s, %s)
            RETURNING id, query, origin, status, error,
                      created_at, updated_at, finished_at
            """,
            (uuid4(), normalized_owner_id, normalized_query),
        )

    if row is None:
        raise RuntimeError("Search session insert did not return a row.")
    return _search_session_to_dict(row)


async def complete_search_session(
    search_id: UUID,
    owner_id: str,
    *,
    origin: SearchOrigin,
    status: SearchStatus = "completed",
    error: str = "",
) -> dict[str, object]:
    """Move a running search to one terminal state without overwriting it."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _complete_search_session(
            connection,
            search_id,
            owner_id,
            origin=origin,
            status=status,
            error=error,
        )

    if row is None:
        raise RuntimeError("Search session is missing or already completed.")
    return _search_session_to_dict(row)


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
                updated_at = NOW(),
                finished_at = NOW()
            WHERE status = 'running'
            RETURNING id
            """,
        )
        return len(rows)


async def _complete_search_session(
    connection: AsyncConnection[DictRow],
    search_id: UUID,
    owner_id: str,
    *,
    origin: SearchOrigin,
    status: SearchStatus,
    error: str = "",
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
            updated_at = NOW(),
            finished_at = NOW()
        WHERE id = %s AND owner_id = %s AND status = 'running'
        RETURNING id, query, origin, status, error,
                  created_at, updated_at, finished_at
        """,
        (origin, status, normalized_error, search_id, _normalized_owner_id(owner_id)),
    )


def _search_session_to_dict(row: Row) -> dict[str, object]:
    return {
        "id": UUID(str(row["id"])),
        "query": str(row["query"]),
        "origin": str(row["origin"]),
        "status": str(row["status"]),
        "error": str(row["error"]),
        "created_at": _format_timestamp(row["created_at"]),
        "updated_at": _format_timestamp(row["updated_at"]),
        "finished_at": _format_optional_timestamp(row["finished_at"]),
    }


def _normalized_owner_id(owner_id: str) -> str:
    normalized_owner_id = owner_id.strip()
    if not normalized_owner_id:
        raise ValueError("Search owner ID is required.")
    if normalized_owner_id != owner_id or len(normalized_owner_id) > 200:
        raise ValueError("Search owner ID must be trimmed and at most 200 characters.")
    return normalized_owner_id
