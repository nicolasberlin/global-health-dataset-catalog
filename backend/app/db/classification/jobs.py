"""Claim, transition and recover persisted candidate classification attempts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.classification.candidates import (
    _CANDIDATE_COLUMNS,
    _RETURNING_CANDIDATE_COLUMNS,
    _repository_candidate_to_dict,
)
from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.execution.worker_claims import read_worker_claim, record_worker_claim
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from app.db.serialization import (
    _jsonb,
)
from collector.classification.repository import RepositoryClassification
from collector.diagnostics import Diagnostic


async def claim_candidate_classification(
    *, claim_token: UUID | None = None,
) -> dict[str, object] | None:
    """Internal worker claim; ownership comes from the persisted search session."""

    claim_token = claim_token or uuid4()
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            receipt = await read_worker_claim(connection, claim_token, "classification")
            if receipt is not None:
                row = await _fetchone(
                    connection,
                    f"""SELECT {_CANDIDATE_COLUMNS}, session.owner_id
                        FROM repository_candidates AS candidate
                        JOIN search_sessions AS session ON session.id = candidate.search_session_id
                        WHERE candidate.id = %s AND candidate.classification_status = 'classifying'
                          AND candidate.updated_at = %s""",
                    (UUID(receipt["resource_id"]), receipt["claim_version"]),
                )
                return (
                    {**_repository_candidate_to_dict(row), "owner_id": str(row["owner_id"])}
                    if row else None
                )
            row = await _fetchone(
                connection,
                f"""
                UPDATE repository_candidates AS candidate
                SET classification_status = 'classifying', updated_at = NOW(),
                    retry_started_at = COALESCE(candidate.retry_started_at, NOW()),
                    next_retry_at = NULL, errors = '[]'::jsonb
                FROM search_sessions AS session
                WHERE candidate.id = (
                    SELECT id FROM repository_candidates
                    WHERE classification_status = 'queued'
                      AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                    ORDER BY updated_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                ) AND candidate.search_session_id = session.id
                  AND candidate.classification_status = 'queued'
                RETURNING {_CANDIDATE_COLUMNS}, session.owner_id
            """,
            )
            if row is not None:
                await record_worker_claim(
                    connection, claim_token, "classification", row["id"], row["updated_at"],
                )
    if row is None:
        return None
    return {**_repository_candidate_to_dict(row), "owner_id": str(row["owner_id"])}


async def _complete_candidate_classification(
    connection: AsyncConnection[DictRow],
    candidate_id: UUID,
    owner_id: str,
    classification: RepositoryClassification,
    *, expected_updated_at: datetime | None = None,
) -> dict[str, object] | None:
    """Persist a decision within the transaction that also reserves its collection."""

    status = "accepted" if classification.accepted else "rejected"
    row = await _fetchone(
        connection,
        f"""
        UPDATE repository_candidates AS candidate
        SET classification_status = %s,
            classification = %s,
            error = '', errors = '[]'::jsonb,
            updated_at = NOW()
        FROM search_sessions AS session
        WHERE candidate.id = %s
          AND candidate.search_session_id = session.id
          AND session.owner_id = %s
          AND candidate.classification_status = 'classifying'
          AND (%s::timestamptz IS NULL OR candidate.updated_at = %s)
        RETURNING {_RETURNING_CANDIDATE_COLUMNS}
        """,
        (
            status,
            _jsonb(asdict(classification)),
            candidate_id,
            validate_owner_id(owner_id),
            expected_updated_at,
            expected_updated_at,
        ),
    )
    if row is None:
        if expected_updated_at is not None:
            return None
        raise RuntimeError("Candidate is missing or is not being classified.")
    return _repository_candidate_to_dict(row)


async def fail_candidate_classification(
    candidate_id: UUID,
    owner_id: str,
    error: str,
    *, errors: list[dict] | None = None, expected_updated_at: datetime | None = None,
) -> dict[str, object] | None:
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
                error = %s, errors = %s,
                updated_at = NOW()
            FROM search_sessions AS session
            WHERE candidate.id = %s
              AND candidate.search_session_id = session.id
              AND session.owner_id = %s
              AND candidate.classification_status = 'classifying'
              AND (%s::timestamptz IS NULL OR candidate.updated_at = %s)
            RETURNING {_RETURNING_CANDIDATE_COLUMNS}
            """,
            (normalized_error, _jsonb(errors or [Diagnostic("processing_failed",
                                                          "classification").to_dict()]),
             candidate_id, validate_owner_id(owner_id),
             expected_updated_at, expected_updated_at),
        )
    if row is None:
        if expected_updated_at is not None:
            return None
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
                errors = %s,
                updated_at = NOW()
            WHERE classification_status = 'classifying'
            RETURNING id
            """,
            (_jsonb([Diagnostic("processing_interrupted", "classification").to_dict()]),),
        )
    return len(rows)
