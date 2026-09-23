from __future__ import annotations

from .db.api_quotas import APIQuotaDecision, consume_api_quota
from .db.classification_completion import (
    CandidateClassificationCompletion,
    complete_candidate_classification,
)
from .db.collected_datasets import (
    get_collected_datasets,
    list_collected_datasets,
    list_dataset_discovery_observations,
    normalize_dataset_search_query,
    save_collected_datasets,
    search_collected_datasets,
)
from .db.collection_completion import complete_collection_job
from .db.collection_jobs import (
    CollectionJobReservation,
    claim_pending_collection_job,
    create_collection_job,
    get_candidate_collection,
    get_collection_job,
    get_collection_job_for_owner,
    mark_collection_job_done,
    mark_collection_job_error,
    mark_collection_job_running,
    mark_interrupted_collection_jobs_error,
    reserve_repository_candidate_collection_job,
)
from .db.connection import close_database_pool, open_database_pool
from .db.repository_candidates import (
    claim_candidate_classification,
    complete_search_session_with_repository_candidates,
    enqueue_candidate_classification,
    fail_candidate_classification,
    get_repository_candidate,
    latest_repository_analysis,
    mark_interrupted_candidate_classifications_error,
    save_repository_candidates,
)
from .db.schema import init_database
from .db.search_sessions import (
    complete_search_session,
    create_search_session,
    mark_interrupted_search_sessions_error,
)
from .db.serialization import StoredJSONError, StoredTimestampError

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
    "get_candidate_collection",
    "get_collection_job_for_owner",
    "get_repository_candidate",
    "init_database",
    "get_collected_datasets",
    "list_collected_datasets",
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
    "enqueue_candidate_classification",
    "claim_candidate_classification",
    "latest_repository_analysis",
)
