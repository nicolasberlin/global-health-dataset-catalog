"""Convenient database operations for isolated test fixtures only.

Production modules import their operations directly from app.db.
"""

from __future__ import annotations

from app.db.catalog.datasets import get_collected_datasets, save_collected_datasets
from app.db.catalog.observations import list_dataset_discovery_observations
from app.db.catalog.search import normalize_dataset_search_query, search_collected_datasets
from app.db.classification.candidates import save_repository_candidates
from app.db.classification.completion import (
    CandidateClassificationCompletion,
    complete_candidate_classification,
)
from app.db.classification.jobs import (
    claim_candidate_classification,
    fail_candidate_classification,
    mark_interrupted_candidate_classifications_error,
)
from app.db.collection.completion import complete_collection_job, mark_collection_job_done
from app.db.collection.job_queries import get_collection_job, get_collection_job_for_owner
from app.db.collection.jobs import (
    claim_pending_collection_job,
    mark_collection_job_error,
    mark_collection_job_running,
    mark_interrupted_collection_jobs_error,
)
from app.db.collection.reservations import (
    CollectionJobReservation,
    reserve_repository_candidate_collection_job,
)
from app.db.connection import close_database_pool, open_database_pool
from app.db.execution.quotas import APIQuotaDecision, consume_api_quota
from app.db.schema import init_database, validate_database_schema
from app.db.search.completion import (
    complete_search_session,
    complete_search_session_with_repository_candidates,
)
from app.db.search.jobs import mark_interrupted_search_sessions_error
from app.db.search.sessions import create_search_session
from app.db.serialization import StoredJSONError, StoredTimestampError

__all__ = (
    "APIQuotaDecision",
    "CollectionJobReservation",
    "CandidateClassificationCompletion",
    "StoredJSONError",
    "StoredTimestampError",
    "close_database_pool",
    "claim_pending_collection_job",
    "complete_collection_job",
    "complete_candidate_classification",
    "complete_search_session",
    "complete_search_session_with_repository_candidates",
    "consume_api_quota",
    "create_legacy_source_job",
    "create_record_job",
    "create_search_session",
    "fail_candidate_classification",
    "get_collection_job",
    "get_collection_job_for_owner",
    "init_database",
    "validate_database_schema",
    "get_collected_datasets",
    "list_dataset_discovery_observations",
    "mark_interrupted_collection_jobs_error",
    "mark_interrupted_search_sessions_error",
    "mark_interrupted_candidate_classifications_error",
    "mark_collection_job_done",
    "mark_collection_job_error",
    "mark_collection_job_running",
    "normalize_dataset_search_query",
    "open_database_pool",
    "reserve_repository_candidate_collection_job",
    "save_repository_candidates",
    "save_collected_datasets",
    "search_collected_datasets",
    "claim_candidate_classification",
)


async def create_legacy_source_job(source_url):
    """Seed an old source job for serialization, ownership and recovery regressions only."""
    from app.db.collection.job_queries import _collection_job_to_dict
    from app.db.collection.jobs import _insert_collection_job
    from app.db.connection import _require_database_pool

    from collector.url_utils import require_http_url

    async with _require_database_pool().connection() as connection:
        row = await _insert_collection_job(connection, require_http_url(source_url), kind="source")
    return _collection_job_to_dict(row)


async def create_record_job(source_url):
    """Create a real accepted candidate and reserve its normal collection follow-up."""
    import sys

    from helpers.workflows import candidate_for, decision

    candidate = await candidate_for(sys.modules[__name__], "local-user", url=source_url)
    completed = await complete_candidate_classification(
        candidate["id"], "local-user", decision(),
    )
    return completed.collection.job
