from __future__ import annotations

from .db_collected_datasets import (
    list_collected_datasets,
    list_dataset_discovery_observations,
    save_collected_datasets,
)
from .db_collection_jobs import (
    create_collection_job,
    get_collection_job,
    mark_collection_job_done,
    mark_collection_job_error,
    mark_collection_job_running,
)
from .db_connection import close_database_pool, open_database_pool
from .db_schema import DATA_SOURCE_KEY_PATTERN_TEXT, init_database
from .db_serialization import StoredJSONError, StoredTimestampError
from .db_sources import (
    DuplicateDataSourceKeyError,
    InvalidDataSourceKeyError,
    InvalidDataSourceURLError,
    ReservedDataSourceKeyError,
    create_data_source,
    get_data_source,
    list_data_sources,
    normalize_data_source_key,
    normalize_data_source_page_url,
    upsert_collector_data_source,
    upsert_data_source,
)

__all__ = (
    "DATA_SOURCE_KEY_PATTERN_TEXT",
    "DuplicateDataSourceKeyError",
    "InvalidDataSourceKeyError",
    "InvalidDataSourceURLError",
    "ReservedDataSourceKeyError",
    "StoredJSONError",
    "StoredTimestampError",
    "close_database_pool",
    "create_collection_job",
    "create_data_source",
    "get_collection_job",
    "get_data_source",
    "init_database",
    "list_collected_datasets",
    "list_data_sources",
    "list_dataset_discovery_observations",
    "mark_collection_job_done",
    "mark_collection_job_error",
    "mark_collection_job_running",
    "normalize_data_source_key",
    "normalize_data_source_page_url",
    "open_database_pool",
    "save_collected_datasets",
    "upsert_collector_data_source",
    "upsert_data_source",
)
