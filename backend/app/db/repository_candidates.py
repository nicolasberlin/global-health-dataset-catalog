"""Durable repository candidates and atomic classification transitions."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from collector.classification.repository import RepositoryClassification
from collector.repository_search.models import RepositorySearchResult
from collector.url_utils import require_http_url

from .connection import Row, _fetchall, _fetchone, _require_database_pool
from .schema import _require_current_schema
from .search_sessions import SearchStatus, _complete_search_session, _normalized_owner_id
from .serialization import (
    _deserialize_json_array,
    _deserialize_signals,
    _format_timestamp,
    _jsonb,
)


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


async def complete_search_session_with_repository_candidates(
    search_id: UUID,
    owner_id: str,
    candidates: list[RepositorySearchResult],
    *,
    status: SearchStatus,
) -> list[dict[str, object]]:
    """Persist and enqueue online candidates, then finish their search atomically."""

    if status not in {"completed", "partial"}:
        raise ValueError("An online candidate search must complete or be partial.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            rows = await _save_repository_candidates(
                connection,
                search_id,
                owner_id,
                candidates,
            )
            session_row = await _complete_search_session(
                connection,
                search_id,
                owner_id,
                origin="online",
                status=status,
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
        (search_id, _normalized_owner_id(owner_id)),
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


async def get_repository_candidate(
    candidate_id: UUID,
    owner_id: str,
) -> dict[str, object] | None:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _get_repository_candidate_row(connection, candidate_id, owner_id)
    return _repository_candidate_to_dict(row) if row else None


async def enqueue_candidate_classification(
    candidate_id: UUID,
    owner_id: str,
    *,
    retry: bool = False,
) -> dict[str, object] | None:
    """Persist an explicit request; discoveries alone are never consumed by workers."""

    eligible_statuses = ("pending", "error") if retry else ("pending",)
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            f"""
            UPDATE repository_candidates AS candidate
            SET classification_status = 'queued',
                classification = NULL,
                error = '',
                updated_at = NOW()
            FROM search_sessions AS session
            WHERE candidate.id = %s
              AND candidate.search_session_id = session.id
              AND session.owner_id = %s
              AND candidate.classification_status = ANY(%s)
            RETURNING {_RETURNING_CANDIDATE_COLUMNS}
            """,
            (candidate_id, _normalized_owner_id(owner_id), list(eligible_statuses)),
        )
    return _repository_candidate_to_dict(row) if row else None


async def claim_candidate_classification() -> dict[str, object] | None:
    """Internal worker claim; ownership comes from the persisted search session."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            f"""
            UPDATE repository_candidates AS candidate
            SET classification_status = 'classifying', updated_at = NOW()
            FROM search_sessions AS session
            WHERE candidate.id = (
                SELECT id FROM repository_candidates
                WHERE classification_status = 'queued'
                ORDER BY updated_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            ) AND candidate.search_session_id = session.id
              AND candidate.classification_status = 'queued'
            RETURNING {_CANDIDATE_COLUMNS}, session.owner_id
        """,
        )
    if row is None:
        return None
    return {**_repository_candidate_to_dict(row), "owner_id": str(row["owner_id"])}


async def latest_repository_analysis(owner_id: str) -> list[dict[str, object]]:
    """Restore the owner's most recent search containing repository candidates."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _fetchall(
            connection,
            f"""
            SELECT {_CANDIDATE_COLUMNS}
            FROM repository_candidates AS candidate
            JOIN search_sessions AS session ON session.id = candidate.search_session_id
            WHERE session.id = (
                SELECT search.id FROM search_sessions AS search
                WHERE search.owner_id = %s AND EXISTS (
                    SELECT 1 FROM repository_candidates WHERE search_session_id = search.id
                )
                ORDER BY search.created_at DESC, search.id DESC LIMIT 1
            ) AND session.owner_id = %s
            ORDER BY candidate.created_at, candidate.id
        """,
            (_normalized_owner_id(owner_id), _normalized_owner_id(owner_id)),
        )
    return [_repository_candidate_to_dict(row) for row in rows]


async def _complete_candidate_classification(
    connection: AsyncConnection[DictRow],
    candidate_id: UUID,
    owner_id: str,
    classification: RepositoryClassification,
) -> dict[str, object]:
    """Persist a decision within the transaction that also reserves its collection."""

    status = "accepted" if classification.accepted else "rejected"
    row = await _fetchone(
        connection,
        f"""
        UPDATE repository_candidates AS candidate
        SET classification_status = %s,
            classification = %s,
            error = '',
            updated_at = NOW()
        FROM search_sessions AS session
        WHERE candidate.id = %s
          AND candidate.search_session_id = session.id
          AND session.owner_id = %s
          AND candidate.classification_status = 'classifying'
        RETURNING {_RETURNING_CANDIDATE_COLUMNS}
        """,
        (
            status,
            _jsonb(asdict(classification)),
            candidate_id,
            _normalized_owner_id(owner_id),
        ),
    )
    if row is None:
        raise RuntimeError("Candidate is missing or is not being classified.")
    return _repository_candidate_to_dict(row)


async def fail_candidate_classification(
    candidate_id: UUID,
    owner_id: str,
    error: str,
) -> dict[str, object]:
    """Record an operational classifier failure without treating it as rejection."""

    normalized_error = error.strip()
    if not normalized_error:
        raise ValueError("Candidate classification error cannot be empty.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            f"""
            UPDATE repository_candidates AS candidate
            SET classification_status = 'error',
                classification = NULL,
                error = %s,
                updated_at = NOW()
            FROM search_sessions AS session
            WHERE candidate.id = %s
              AND candidate.search_session_id = session.id
              AND session.owner_id = %s
              AND candidate.classification_status = 'classifying'
            RETURNING {_RETURNING_CANDIDATE_COLUMNS}
            """,
            (normalized_error, candidate_id, _normalized_owner_id(owner_id)),
        )
    if row is None:
        raise RuntimeError("Candidate is missing or is not being classified.")
    return _repository_candidate_to_dict(row)


async def mark_interrupted_candidate_classifications_error() -> int:
    """Make classifications interrupted by process restart explicitly retryable."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _fetchall(
            connection,
            """
            UPDATE repository_candidates
            SET classification_status = 'error',
                classification = NULL,
                error = 'Classification interrupted by application restart.',
                updated_at = NOW()
            WHERE classification_status = 'classifying'
            RETURNING id
            """,
        )
    return len(rows)


async def _get_repository_candidate_row(
    connection: AsyncConnection[DictRow],
    candidate_id: UUID,
    owner_id: str,
) -> Row | None:
    return await _fetchone(
        connection,
        f"""
        SELECT {_CANDIDATE_COLUMNS}
        FROM repository_candidates AS candidate
        JOIN search_sessions AS session ON session.id = candidate.search_session_id
        WHERE candidate.id = %s AND session.owner_id = %s
        """,
        (candidate_id, _normalized_owner_id(owner_id)),
    )


_CANDIDATE_COLUMNS = """
    candidate.id, candidate.search_session_id, session.query AS search_query,
    candidate.title, candidate.description, candidate.url, candidate.source,
    candidate.publisher, candidate.publication_date, candidate.doi,
    candidate.keywords, candidate.metadata, candidate.classification_status,
    candidate.classification, candidate.error, candidate.created_at,
    candidate.updated_at
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
        "classification": (
            None
            if classification is None
            else _deserialize_signals(
                classification,
                "repository_candidates.classification",
            )
        ),
        "error": str(row["error"]),
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
