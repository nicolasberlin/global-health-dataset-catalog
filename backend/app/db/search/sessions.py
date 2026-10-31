"""Create, retrieve and represent persisted search session records."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from app.db.connection import Row, _fetchone, _require_database_pool
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from app.db.serialization import _format_optional_timestamp, _format_timestamp

SearchOrigin = Literal["database", "online"]


SearchStatus = Literal["completed", "partial", "error"]


async def create_search_session(query: str, owner_id: str) -> dict[str, object]:
    """Create the durable record that owns one local-then-online search."""

    normalized_query = query.strip()
    normalized_owner_id = validate_owner_id(owner_id)
    if not normalized_query:
        raise ValueError("Search query is required.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            INSERT INTO search_sessions (id, owner_id, query)
            VALUES (%s, %s, %s)
            RETURNING id, query, origin, status, error, errors,
                  local_result_count, discovery_complete,
                      created_at, updated_at, finished_at
            """,
            (uuid4(), normalized_owner_id, normalized_query),
        )

    if row is None:
        raise RuntimeError("Search session insert did not return a row.")
    return _search_session_to_dict(row)


async def latest_search_id(owner_id, *, with_candidates=False):

    """Return the owner's latest search ID, optionally requiring saved candidates."""
    async with _require_database_pool().connection() as connection:
        candidate_filter = (
            "AND EXISTS (SELECT 1 FROM repository_candidates AS candidate "
            "WHERE candidate.search_session_id = search_sessions.id)"
            if with_candidates else ""
        )
        row = await _fetchone(
            connection,
            f"""
            SELECT id FROM search_sessions WHERE owner_id = %s
            {candidate_filter}
            ORDER BY created_at DESC, id DESC LIMIT 1
        """,
            (validate_owner_id(owner_id),),
        )
    return row["id"] if row else None


def _search_session_to_dict(row: Row) -> dict[str, object]:
    return {
        "id": UUID(str(row["id"])),
        "query": str(row["query"]),
        "origin": str(row["origin"]),
        "status": str(row["status"]),
        "error": str(row["error"]),
        "errors": row.get("errors", []),
        "local_result_count": row.get("local_result_count"),
        "discovery_complete": row.get("discovery_complete"),
        "created_at": _format_timestamp(row["created_at"]),
        "updated_at": _format_timestamp(row["updated_at"]),
        "finished_at": _format_optional_timestamp(row["finished_at"]),
    }
