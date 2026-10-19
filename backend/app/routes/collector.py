"""Collector router composition and compatibility imports for Python consumers."""

from fastapi import APIRouter

from app.routes.candidates import (
    _candidate_with_collection,
    classify_repository_result,
    read_latest_repository_analysis,
    read_repository_candidate,
)
from app.routes.candidates import (
    router as candidates_router,
)
from app.routes.catalog import list_collected, read_collected_by_id
from app.routes.catalog import router as catalog_router
from app.routes.collection_jobs import (
    read_collection_job,
    retry_collection_job,
)
from app.routes.collection_jobs import (
    router as jobs_router,
)
from app.routes.collector_presenters import (
    _collector_collected_dataset,
    _collector_repository_candidate,
    _collector_validation,
)
from app.routes.diagnostics import router as diagnostics_router
from app.routes.searches import (
    create_search,
    latest_search,
    retry_search,
    search_datasets,
    search_progress,
)
from app.routes.searches import (
    router as searches_router,
)

router = APIRouter(prefix="/collector")
for child_router in (
    catalog_router,
    jobs_router,
    candidates_router,
    searches_router,
    diagnostics_router,
):
    router.include_router(child_router)

__all__ = [
    "router",
    "create_search",
    "latest_search",
    "retry_search",
    "search_datasets",
    "search_progress",
    "classify_repository_result",
    "read_latest_repository_analysis",
    "read_repository_candidate",
    "list_collected",
    "read_collected_by_id",
    "read_collection_job",
    "retry_collection_job",
    "_candidate_with_collection",
    "_collector_collected_dataset",
    "_collector_repository_candidate",
    "_collector_validation",
]
