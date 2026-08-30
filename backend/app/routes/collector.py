from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.database import create_collection_job as db_create_collection_job
from app.database import (
    get_collection_job,
    list_collected_datasets,
    mark_collection_job_done,
    mark_collection_job_error,
    mark_collection_job_running,
    save_collected_datasets,
)
from app.routes.collector_schemas import (
    CollectorAnalyzeHTMLRequest,
    CollectorAnalyzeHTMLResponse,
    CollectorCollectedDataset,
    CollectorCollectionJob,
    CollectorCollectionJobResponse,
    CollectorCollectionResponse,
    CollectorCollectURLRequest,
    CollectorDiscoveredPage,
    CollectorDiscoveryResponse,
    CollectorDistribution,
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
    CollectorRepositorySearchResponse,
    CollectorRepositorySearchWarning,
    CollectorURLRequest,
    CollectorValidation,
)
from collector.classification.factory import (
    build_default_page_classifier,
    build_default_repository_result_classifier,
)
from collector.classification.page import PageClassificationError, PageClassifier
from collector.classification.repository import (
    MAX_REPOSITORY_DATE_CHARS,
    MAX_REPOSITORY_DESCRIPTION_CHARS,
    MAX_REPOSITORY_DOI_CHARS,
    MAX_REPOSITORY_KEYWORD_CHARS,
    MAX_REPOSITORY_KEYWORDS,
    MAX_REPOSITORY_METADATA_BYTES,
    MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS,
    MAX_REPOSITORY_METADATA_VALUE_CHARS,
    MAX_REPOSITORY_PUBLISHER_CHARS,
    MAX_REPOSITORY_SEARCH_QUERY_CHARS,
    MAX_REPOSITORY_SOURCE_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
)
from collector.config import DEFAULT_CONFIG
from collector.discovery.manager import discover_source
from collector.extraction.dataset_metadata import normalize_dataset_metadata
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import fetch_public_html
from collector.main import collect_source, collect_source_with_report
from collector.repository_search import (
    RepositorySearchResult,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.repository_search import (
    classify_repository_result as classify_one_repository_result,
)
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

router = APIRouter(prefix="/collector", tags=["collector"])
logger = logging.getLogger(__name__)

REPOSITORY_CLASSIFICATION_MAX_CONCURRENCY = 2
# A dedicated executor keeps the strict limit until synchronous LLM work really
# finishes, even when the awaiting HTTP request is cancelled.
_repository_classification_executor = ThreadPoolExecutor(
    max_workers=REPOSITORY_CLASSIFICATION_MAX_CONCURRENCY,
    thread_name_prefix="repository-classification",
)


@router.post("/analyze-html")
async def analyze_html(
    payload: CollectorAnalyzeHTMLRequest,
) -> CollectorAnalyzeHTMLResponse:
    return await asyncio.to_thread(_analyze_html, str(payload.url), payload.html)


@router.post("/analyze-url")
async def analyze_url(payload: CollectorURLRequest) -> CollectorAnalyzeHTMLResponse:
    try:
        fetched_page = await asyncio.to_thread(fetch_public_html, str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return await asyncio.to_thread(_analyze_html, fetched_page.final_url, fetched_page.html)


@router.post("/discover-url")
async def discover_url(payload: CollectorURLRequest) -> CollectorDiscoveryResponse:
    try:
        discovered_pages = await asyncio.to_thread(discover_source, str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return CollectorDiscoveryResponse(
        items=[
            CollectorDiscoveredPage(
                url=page.url,
                discovery_method=page.discovery_method,
                priority=page.priority,
                title=page.title,
                description=page.description,
                publisher=page.publisher,
                geography=list(page.geography),
                discovery_metadata=page.discovery_metadata,
                distributions=[
                    _collector_distribution(distribution)
                    for distribution in page.distributions
                ],
            )
            for page in discovered_pages
        ]
    )


@router.post("/collection-jobs", status_code=202)
async def start_collection_job(
    payload: CollectorURLRequest,
    background_tasks: BackgroundTasks,
) -> CollectorCollectionJobResponse:
    job = await db_create_collection_job(str(payload.url))
    background_tasks.add_task(_run_collection_job, int(job["id"]), str(payload.url))

    return CollectorCollectionJobResponse(job=CollectorCollectionJob(**job))


@router.get("/collection-jobs/{job_id}")
async def read_collection_job(job_id: int) -> CollectorCollectionJobResponse:
    job = await get_collection_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")

    return CollectorCollectionJobResponse(job=CollectorCollectionJob(**job))


@router.post("/collect-url")
async def collect_url(payload: CollectorCollectURLRequest) -> CollectorCollectionResponse:
    try:
        collected_datasets = await asyncio.to_thread(collect_source, str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception
    except PageClassificationError as exception:
        raise HTTPException(status_code=502, detail="Page classification failed.") from exception

    if payload.save:
        collected_datasets = await save_collected_datasets(
            str(payload.url),
            collected_datasets,
        )

    return CollectorCollectionResponse(
        items=[_collector_collected_dataset(dataset) for dataset in collected_datasets],
        saved=payload.save,
        saved_count=len(collected_datasets) if payload.save else 0,
    )


@router.get("/collected-datasets")
async def list_collected() -> CollectorCollectionResponse:
    return CollectorCollectionResponse(
        items=[
            _collector_collected_dataset(dataset)
            for dataset in await list_collected_datasets()
        ],
        saved=False,
        saved_count=0,
    )


@router.post("/search-repositories")
async def search_repositories(
    payload: CollectorRepositorySearchRequest,
) -> CollectorRepositorySearchResponse:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query is required")

    try:
        search_response = await asyncio.to_thread(search_repository_metadata, query)
    except ValueError as exception:
        raise HTTPException(status_code=502, detail="Repository search failed.") from exception

    return CollectorRepositorySearchResponse(
        query=query,
        items=[
            _collector_repository_search_item(item, search_query=query)
            for item in search_response.results
        ],
        warnings=[
            _collector_repository_search_warning(warning)
            for warning in search_response.warnings
        ],
    )


@router.post("/classify-repository-result")
async def classify_repository_result(
    payload: CollectorRepositorySearchItem,
) -> CollectorRepositorySearchItem:
    if not payload.search_query.strip():
        raise HTTPException(status_code=400, detail="Search query is required")

    result = _repository_search_result_from_item(payload)
    try:
        classified_result = await asyncio.get_running_loop().run_in_executor(
            _repository_classification_executor,
            classify_one_repository_result,
            result,
            build_default_repository_result_classifier(DEFAULT_CONFIG),
        )
    except PageClassificationError as exception:
        logger.exception(
            "Repository result classification failed for source=%r url=%s",
            result.source,
            result.url,
        )
        raise HTTPException(status_code=502, detail="Page classification failed.") from exception

    return _collector_repository_search_item(classified_result)


async def _run_collection_job(job_id: int, source_url: str) -> None:
    try:
        running_job = await mark_collection_job_running(job_id)
        if running_job is None:
            return

        collection_result = await asyncio.to_thread(
            collect_source_with_report,
            source_url,
        )
        saved_datasets = await save_collected_datasets(
            source_url,
            collection_result.datasets,
            collection_job_id=job_id,
        )
        await mark_collection_job_done(job_id, len(saved_datasets), collection_result.report)
    except Exception as exception:  # noqa: BLE001 - background jobs must persist failures.
        await mark_collection_job_error(job_id, str(exception))


def _analyze_html(
    url: str,
    html: str,
    classifier: PageClassifier | None = None,
) -> CollectorAnalyzeHTMLResponse:
    page = extract_page(url, html)
    distributions = extract_distributions(page)
    try:
        page_classifier = (
            classifier
            if classifier is not None
            else build_default_page_classifier(DEFAULT_CONFIG)
        )
        classification = page_classifier.classify(page, distributions)
    except PageClassificationError as exception:
        raise HTTPException(status_code=502, detail="Page classification failed.") from exception

    return CollectorAnalyzeHTMLResponse(
        accepted=classification.accepted,
        dataset_url=page.canonical_url,
        title=page.title or page.h1 or page.canonical_url,
        description=page.meta_description or page.og_description,
        publisher=page.publisher,
        hosting_platform=page.hosting_platform,
        uploader=page.uploader,
        geography=list(page.geography),
        dataset_probability=classification.dataset_probability,
        dataset_signals=classification.dataset_signals,
        health_probability=classification.health_probability,
        health_label=classification.health_label,
        health_signals=classification.health_signals,
        distributions=[
            _collector_distribution(distribution)
            for distribution in distributions
        ],
    )


def _collector_distribution(distribution: DistributionCandidate) -> CollectorDistribution:
    return CollectorDistribution(
        url=distribution.url,
        format=distribution.format,
        probability=distribution.probability,
        anchor=distribution.anchor,
        mime_type=distribution.mime_type,
        first_seen_at=distribution.first_seen_at,
        last_seen_at=distribution.last_seen_at,
        last_checked_at=distribution.last_checked_at,
    )


def _collector_repository_search_item(
    item: RepositorySearchResult,
    *,
    search_query: str | None = None,
) -> CollectorRepositorySearchItem:
    data = asdict(item)
    if search_query is not None and not data.get("search_query"):
        data["search_query"] = search_query
    data["title"] = str(data.get("title", ""))[:MAX_REPOSITORY_TITLE_CHARS]
    data["description"] = str(data.get("description", ""))[
        :MAX_REPOSITORY_DESCRIPTION_CHARS
    ]
    data["source"] = str(data.get("source", ""))[:MAX_REPOSITORY_SOURCE_CHARS]
    data["search_query"] = str(data.get("search_query", ""))[
        :MAX_REPOSITORY_SEARCH_QUERY_CHARS
    ]
    data["publisher"] = str(data.get("publisher", ""))[
        :MAX_REPOSITORY_PUBLISHER_CHARS
    ]
    data["date"] = str(data.get("date", ""))[:MAX_REPOSITORY_DATE_CHARS]
    data["doi"] = str(data.get("doi", ""))[:MAX_REPOSITORY_DOI_CHARS]
    data["keywords"] = [
        str(keyword)[:MAX_REPOSITORY_KEYWORD_CHARS]
        for keyword in data.get("keywords", [])[:MAX_REPOSITORY_KEYWORDS]
    ]
    data["metadata"] = _bounded_repository_metadata(data.get("metadata"))
    return CollectorRepositorySearchItem(**data)


def _bounded_repository_metadata(value: object) -> dict[str, str]:
    metadata = normalize_dataset_metadata(value if isinstance(value, dict) else {})
    bounded_metadata = {
        key: text[
            :(
                MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS
                if key == "Description of dataset"
                else MAX_REPOSITORY_METADATA_VALUE_CHARS
            )
        ]
        for key, text in metadata.items()
    }

    while _json_size_bytes(bounded_metadata) > MAX_REPOSITORY_METADATA_BYTES:
        largest_key = max(bounded_metadata, key=lambda key: len(bounded_metadata[key]))
        largest_value = bounded_metadata[largest_key]
        if not largest_value:
            break
        bounded_metadata[largest_key] = largest_value[: len(largest_value) // 2]

    return bounded_metadata


def _json_size_bytes(value: dict[str, str]) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _repository_search_result_from_item(
    item: CollectorRepositorySearchItem,
) -> RepositorySearchResult:
    return RepositorySearchResult(
        title=item.title,
        description=item.description,
        url=str(item.url),
        source=item.source,
        search_query=item.search_query,
        publisher=item.publisher,
        date=item.date,
        doi=item.doi,
        keywords=list(item.keywords),
        relevance_score=item.relevance_score,
        metadata=dict(item.metadata),
    )


def _collector_repository_search_warning(
    warning: RepositorySearchWarning,
) -> CollectorRepositorySearchWarning:
    return CollectorRepositorySearchWarning(**asdict(warning))


def _collector_validation(validation: ValidationResult) -> CollectorValidation:
    return CollectorValidation(
        url=validation.url,
        final_url=validation.final_url,
        format=validation.format,
        ok=validation.ok,
        http_status=validation.http_status,
        mime_type=validation.mime_type,
        size_bytes=validation.size_bytes,
        etag=validation.etag,
        last_modified=validation.last_modified,
        content_disposition=validation.content_disposition,
        error=validation.error,
    )


def _collector_collected_dataset(dataset: CollectedDataset) -> CollectorCollectedDataset:
    return CollectorCollectedDataset(
        id=dataset.database_id,
        source_url=dataset.source_url,
        dataset_url=dataset.dataset_url,
        title=dataset.title,
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform=dataset.hosting_platform,
        uploader=dataset.uploader,
        geography=list(dataset.geography),
        discovery_method=dataset.discovery_method,
        dataset_probability=dataset.dataset_probability,
        dataset_signals=dataset.dataset_signals,
        health_probability=dataset.health_probability,
        health_label=dataset.health_label,
        health_signals=dataset.health_signals,
        distributions=[
            _collector_distribution(distribution)
            for distribution in dataset.distributions
        ],
        validation_results=[
            _collector_validation(validation)
            for validation in dataset.validation_results
        ],
        first_seen_at=dataset.first_seen_at,
        last_seen_at=dataset.last_seen_at,
        updated_at=dataset.updated_at,
    )
