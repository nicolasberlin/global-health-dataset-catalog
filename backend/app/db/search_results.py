"""Ordered local result identities; dataset records remain in the shared catalogue."""

from .connection import _fetchone


async def save_local_results(connection, search_id, dataset_ids):
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


async def latest_search_id(owner_id):
    from .connection import _require_database_pool
    from .search_sessions import _normalized_owner_id

    async with _require_database_pool().connection() as connection:
        row = await _fetchone(
            connection,
            """
            SELECT id FROM search_sessions WHERE owner_id = %s
            ORDER BY created_at DESC, id DESC LIMIT 1
        """,
            (_normalized_owner_id(owner_id),),
        )
    return row["id"] if row else None
