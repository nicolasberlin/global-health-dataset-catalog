"""Read persisted state for core assertions without optional browsing endpoints."""

from app.db.connection import (
    _fetchall,
    _fetchone,
    _require_database_initialized,
    _require_database_pool,
)
from app.db.repository_candidates import _CANDIDATE_COLUMNS, _repository_candidate_to_dict


async def stored_datasets(database):
    _require_database_initialized()
    async with _require_database_pool().connection() as connection:
        rows = await _fetchall(connection, "SELECT id FROM collected_datasets ORDER BY id DESC")
    result = []
    for offset in range(0, len(rows), 100):
        result.extend(
            await database.get_collected_datasets(
                [row["id"] for row in rows[offset : offset + 100]]
            )
        )
    return result


async def stored_candidate(candidate_id, owner_id):
    _require_database_initialized()
    async with _require_database_pool().connection() as connection:
        row = await _fetchone(
            connection,
            f"SELECT {_CANDIDATE_COLUMNS} FROM repository_candidates AS candidate "
            "JOIN search_sessions AS session ON session.id = candidate.search_session_id "
            "WHERE candidate.id = %s AND session.owner_id = %s",
            (candidate_id, owner_id),
        )
    return _repository_candidate_to_dict(row) if row else None
