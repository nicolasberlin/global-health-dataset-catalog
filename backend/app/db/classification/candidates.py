"""Store repository candidate metadata and reconstruct persisted candidate records."""

from __future__ import annotations

from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.connection import Row, _fetchall, _fetchone, _require_database_pool
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from app.db.serialization import (
    _deserialize_json_array,
    _deserialize_signals,
    _format_timestamp,
    _jsonb,
)
from collector.repository_search.models import RepositorySearchResult
from collector.url_utils import require_http_url


async def save_repository_candidates(
    search_id: UUID,
    owner_id: str,
    candidates: list[RepositorySearchResult],
) -> list[dict[str, object]]:
    """Persist provider results under one search without overwriting duplicates."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            rows = await _save_repository_candidates(
                connection,
                search_id,
                owner_id,
                candidates,
            )
    return [_repository_candidate_to_dict(row) for row in rows]


async def _save_repository_candidates(
    connection: AsyncConnection[DictRow],
    search_id: UUID,
    owner_id: str,
    candidates: list[RepositorySearchResult],
) -> list[Row]:
    session = await _fetchone(
        connection,
        """
        SELECT id
        FROM search_sessions
        WHERE id = %s AND owner_id = %s
        FOR SHARE
        """,
        (search_id, validate_owner_id(owner_id)),
    )
    if session is None:
        raise ValueError("Search session not found.")

    for candidate in candidates:
        await connection.execute(
            """
            INSERT INTO repository_candidates (
                id, search_session_id, title, description, url, source,
                publisher, publication_date, doi, keywords, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(search_session_id, source, url) DO NOTHING
            """,
            (
                uuid4(),
                search_id,
                _required_text(candidate.title, "Candidate title"),
                candidate.description.strip(),
                require_http_url(candidate.url),
                _required_text(candidate.source, "Candidate source"),
                candidate.publisher.strip(),
                candidate.date.strip(),
                candidate.doi.strip(),
                _jsonb(_normalized_keywords(candidate.keywords)),
                _jsonb(candidate.metadata),
            ),
        )

    return await _fetchall(
        connection,
        f"""
        SELECT {_CANDIDATE_COLUMNS}
        FROM repository_candidates AS candidate
        JOIN search_sessions AS session ON session.id = candidate.search_session_id
        WHERE candidate.search_session_id = %s
        ORDER BY candidate.created_at, candidate.id
        """,
        (search_id,),
    )


_CANDIDATE_COLUMNS = """
    candidate.id, candidate.search_session_id, session.query AS search_query,
    candidate.title, candidate.description, candidate.url, candidate.source,
    candidate.publisher, candidate.publication_date, candidate.doi,
    candidate.keywords, candidate.metadata, candidate.classification_status,
    candidate.classification, candidate.error, candidate.errors, candidate.created_at,
    candidate.updated_at, candidate.classification_progress
"""


_RETURNING_CANDIDATE_COLUMNS = _CANDIDATE_COLUMNS


def _repository_candidate_to_dict(row: Row) -> dict[str, object]:
    classification = row["classification"]
    return {
        "id": UUID(str(row["id"])),
        "search_session_id": UUID(str(row["search_session_id"])),
        "search_query": str(row["search_query"]),
        "title": str(row["title"]),
        "description": str(row["description"]),
        "url": str(row["url"]),
        "source": str(row["source"]),
        "publisher": str(row["publisher"]),
        "publication_date": str(row["publication_date"]),
        "doi": str(row["doi"]),
        "keywords": [
            str(value)
            for value in _deserialize_json_array(
                row["keywords"],
                "repository_candidates.keywords",
                "keywords",
            )
        ],
        "metadata": _deserialize_signals(
            row["metadata"],
            "repository_candidates.metadata",
        ),
        "classification_status": str(row["classification_status"]),
        "classification_progress": row.get("classification_progress", {}),
        "classification": (
            None
            if classification is None
            else _deserialize_signals(
                classification,
                "repository_candidates.classification",
            )
        ),
        "error": str(row["error"]),
        "errors": row.get("errors", []),
        "created_at": _format_timestamp(row["created_at"]),
        "updated_at": _format_timestamp(row["updated_at"]),
    }


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} cannot be empty.")
    return normalized


def _normalized_keywords(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
