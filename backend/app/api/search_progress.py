"""Shared progress reads for search replies and diagnostic exports.

HTTP handlers provide the server-derived owner and set their response headers.
This helper loads one owner-scoped snapshot and prepares its response without
calling another route, scheduling work or changing persisted state.
"""

from uuid import UUID

from fastapi import HTTPException

from app.api.presenters.search import public_search_progress
from app.api.schemas.search import SearchProgressResponse
from app.db.search.progress import read_search_progress


async def load_search_progress(
    search_id: UUID, owner_id: str,
) -> SearchProgressResponse:
    """Return the owned snapshot; hide absent and foreign searches behind the same 404."""
    snapshot = await read_search_progress(search_id, owner_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return public_search_progress(search_id, snapshot)
