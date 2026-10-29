"""Convenient database operations for isolated test fixtures only.

Production modules import their operations directly from app.db.
"""

from __future__ import annotations

from app.db.catalog import (
    get_collected_datasets,
    list_dataset_discovery_observations,
    normalize_dataset_search_query,
    save_collected_datasets,
    search_collected_datasets,
)
from app.db.classification.candidates import (
    claim_candidate_classification,
    complete_search_session_with_repository_candidates,
    fail_candidate_classification,
    mark_interrupted_candidate_classifications_error,
    save_repository_candidates,
)
from app.db.classification.completion import (
    CandidateClassificationCompletion,
    complete_candidate_classification,
)
from app.db.collection.completion import complete_collection_job
from app.db.collection.jobs import (
    CollectionJobReservation,
    claim_pending_collection_job,
    create_collection_job,
    get_collection_job,
    get_collection_job_for_owner,
    mark_collection_job_done,
    mark_collection_job_error,
    mark_collection_job_running,
    mark_interrupted_collection_jobs_error,
    reserve_repository_candidate_collection_job,
)
from app.db.connection import close_database_pool, open_database_pool
from app.db.execution.quotas import APIQuotaDecision, consume_api_quota
from app.db.schema import init_database, validate_database_schema
from app.db.search.sessions import (
    complete_search_session,
    create_search_session,
    mark_interrupted_search_sessions_error,
)
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
    "create_collection_job",
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
