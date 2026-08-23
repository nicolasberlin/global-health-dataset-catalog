from __future__ import annotations

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
from collector.classification.factory import build_default_page_classifier
from collector.classification.page import PageClassificationError, PageClassifier
from collector.config import DEFAULT_CONFIG
from collector.discovery.manager import discover_source
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import fetch_public_html
from collector.main import collect_source, collect_source_with_report
from collector.repository_search import (
    RepositorySearchResult,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

router = APIRouter(prefix="/collector", tags=["collector"])


@router.post("/analyze-html")
def analyze_html(payload: CollectorAnalyzeHTMLRequest) -> CollectorAnalyzeHTMLResponse:
    return _analyze_html(str(payload.url), payload.html)


@router.post("/analyze-url")
def analyze_url(payload: CollectorURLRequest) -> CollectorAnalyzeHTMLResponse:
    try:
        fetched_page = fetch_public_html(str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return _analyze_html(fetched_page.final_url, fetched_page.html)


@router.post("/discover-url")
def discover_url(payload: CollectorURLRequest) -> CollectorDiscoveryResponse:
    try:
        discovered_pages = discover_source(str(payload.url))
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
                metadata=page.metadata,
                distributions=[
                    _collector_distribution(distribution)
                    for distribution in page.distributions
                ],
            )
            for page in discovered_pages
        ]
    )


@router.post("/collection-jobs", status_code=202)
def start_collection_job(
    payload: CollectorURLRequest,
    background_tasks: BackgroundTasks,
) -> CollectorCollectionJobResponse:
    job = db_create_collection_job(str(payload.url))
    background_tasks.add_task(_run_collection_job, int(job["id"]), str(payload.url))

    return CollectorCollectionJobResponse(job=CollectorCollectionJob(**job))


@router.get("/collection-jobs/{job_id}")
def read_collection_job(job_id: int) -> CollectorCollectionJobResponse:
    job = get_collection_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Collection job not found")

    return CollectorCollectionJobResponse(job=CollectorCollectionJob(**job))


@router.post("/collect-url")
def collect_url(payload: CollectorCollectURLRequest) -> CollectorCollectionResponse:
    try:
        collected_datasets = collect_source(str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception
    except PageClassificationError as exception:
        raise HTTPException(status_code=502, detail="Page classification failed.") from exception

    if payload.save:
        collected_datasets = save_collected_datasets(str(payload.url), collected_datasets)

    return CollectorCollectionResponse(
        items=[_collector_collected_dataset(dataset) for dataset in collected_datasets],
        saved=payload.save,
        saved_count=len(collected_datasets) if payload.save else 0,
    )


@router.get("/collected-datasets")
def list_collected() -> CollectorCollectionResponse:
    return CollectorCollectionResponse(
        items=[
            _collector_collected_dataset(dataset)
            for dataset in list_collected_datasets()
        ],
        saved=False,
        saved_count=0,
    )


@router.post("/search-repositories")
def search_repositories(
    payload: CollectorRepositorySearchRequest,
) -> CollectorRepositorySearchResponse:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query is required")

    try:
        search_response = search_repository_metadata(query)
    except ValueError as exception:
        raise HTTPException(status_code=502, detail="Repository search failed.") from exception

    return CollectorRepositorySearchResponse(
        query=query,
        items=[
            _collector_repository_search_item(item)
            for item in search_response.results
        ],
        warnings=[
            _collector_repository_search_warning(warning)
            for warning in search_response.warnings
        ],
    )


def _run_collection_job(job_id: int, source_url: str) -> None:
    try:
        mark_collection_job_running(job_id)
        collection_result = collect_source_with_report(source_url)
        saved_datasets = save_collected_datasets(
            source_url,
            collection_result.datasets,
            collection_job_id=job_id,
        )
        mark_collection_job_done(job_id, len(saved_datasets), collection_result.report)
    except Exception as exception:  # noqa: BLE001 - background jobs must persist failures.
        mark_collection_job_error(job_id, str(exception))


def _analyze_html(
    url: str,
    html: str,
    classifier: PageClassifier | None = None,
) -> CollectorAnalyzeHTMLResponse:
    page = extract_page(url, html)
    distributions = extract_distributions(page)
    page_classifier = (
        classifier
        if classifier is not None
        else build_default_page_classifier(DEFAULT_CONFIG)
    )

    try:
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
) -> CollectorRepositorySearchItem:
    return CollectorRepositorySearchItem(**asdict(item))


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
