from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.database import list_collected_datasets, save_collected_datasets
from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.config import DEFAULT_CONFIG
from collector.discovery.manager import discover_source
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import fetch_public_html
from collector.main import collect_source
from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

router = APIRouter(prefix="/collector", tags=["collector"])


class CollectorAnalyzeHTMLRequest(BaseModel):
    url: HttpUrl
    html: str = Field(min_length=1)


class CollectorAnalyzeURLRequest(BaseModel):
    url: HttpUrl


class CollectorDiscoverURLRequest(BaseModel):
    url: HttpUrl


class CollectorCollectURLRequest(BaseModel):
    url: HttpUrl
    save: bool = True


class CollectorDistribution(BaseModel):
    url: str
    format: str
    probability: float
    anchor: str = ""
    mime_type: str = ""


class CollectorDiscoveredPage(BaseModel):
    url: str
    discovery_method: str
    priority: float
    title: str = ""
    description: str = ""
    publisher: str = ""
    metadata: dict[str, Any]
    distributions: list[CollectorDistribution]


class CollectorDiscoveryResponse(BaseModel):
    items: list[CollectorDiscoveredPage]


class CollectorValidation(BaseModel):
    url: str
    final_url: str
    format: str
    ok: bool
    http_status: Optional[int]  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    mime_type: str = ""
    size_bytes: Optional[int] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    etag: str = ""
    last_modified: str = ""
    content_disposition: str = ""
    error: str = ""


class CollectorAnalyzeHTMLResponse(BaseModel):
    accepted: bool
    dataset_url: str
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    dataset_probability: float
    dataset_signals: dict[str, Any]
    health_probability: float
    health_label: str
    health_signals: dict[str, Any]
    distributions: list[CollectorDistribution]


class CollectorCollectedDataset(BaseModel):
    id: Optional[int] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    source_url: str = ""
    dataset_url: str
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    discovery_method: str
    dataset_probability: float
    dataset_signals: dict[str, Any]
    health_probability: float
    health_label: str
    health_signals: dict[str, Any]
    distributions: list[CollectorDistribution]
    validation_results: list[CollectorValidation]
    updated_at: str = ""


class CollectorCollectionResponse(BaseModel):
    items: list[CollectorCollectedDataset]
    saved: bool = False
    saved_count: int = 0


@router.post("/analyze-html")
def analyze_html(payload: CollectorAnalyzeHTMLRequest) -> CollectorAnalyzeHTMLResponse:
    return _analyze_html(str(payload.url), payload.html)


@router.post("/analyze-url")
def analyze_url(payload: CollectorAnalyzeURLRequest) -> CollectorAnalyzeHTMLResponse:
    try:
        fetched_page = fetch_public_html(str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return _analyze_html(fetched_page.final_url, fetched_page.html)


@router.post("/discover-url")
def discover_url(payload: CollectorDiscoverURLRequest) -> CollectorDiscoveryResponse:
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


@router.post("/collect-url")
def collect_url(payload: CollectorCollectURLRequest) -> CollectorCollectionResponse:
    try:
        collected_datasets = collect_source(str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

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


def _analyze_html(url: str, html: str) -> CollectorAnalyzeHTMLResponse:
    page = extract_page(url, html)
    distributions = extract_distributions(page)
    dataset_score = score_dataset_page(page, distributions)
    health_score = score_health_page(page)
    accepted = (
        dataset_score.probability >= DEFAULT_CONFIG.min_dataset_probability
        and health_score.probability >= DEFAULT_CONFIG.min_health_probability
    )

    return CollectorAnalyzeHTMLResponse(
        accepted=accepted,
        dataset_url=page.canonical_url,
        title=page.title or page.h1 or page.canonical_url,
        description=page.meta_description or page.og_description,
        publisher=page.publisher,
        hosting_platform=page.hosting_platform,
        uploader=page.uploader,
        dataset_probability=dataset_score.probability,
        dataset_signals=dataset_score.signals,
        health_probability=health_score.probability,
        health_label=health_score.label,
        health_signals=health_score.signals,
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
    )


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
        updated_at=dataset.updated_at,
    )
