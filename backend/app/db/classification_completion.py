"""Commit a classification and its collection reservation as one unit."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from collector.classification.repository import RepositoryClassification

from .collection_jobs import (
    CollectionJobReservation,
    _reserve_repository_candidate_collection_job,
)
from .connection import _require_database_pool
from .repository_candidates import _complete_candidate_classification
from .schema import _require_current_schema


@dataclass(frozen=True)
class CandidateClassificationCompletion:
    candidate: dict[str, object]
    collection: CollectionJobReservation | None


async def complete_candidate_classification(
    candidate_id: UUID,
    owner_id: str,
    classification: RepositoryClassification,
) -> CandidateClassificationCompletion:
    """No accepted decision commits without a saved result or associated job.

    The LLM call has finished before this function. A reservation/association
    failure rolls back the decision as well; the caller may record an error.
    """

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            candidate = await _complete_candidate_classification(
                connection,
                candidate_id,
                owner_id,
                classification,
            )
            collection = None
            if classification.accepted:
                collection = await _reserve_repository_candidate_collection_job(
                    connection,
                    candidate_id,
                    owner_id,
                )
    return CandidateClassificationCompletion(candidate, collection)
