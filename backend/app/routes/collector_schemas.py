from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl


# Manual collector test endpoints: analyze pasted HTML or fetch one URL maybe refator later.
class CollectorAnalyzeHTMLRequest(BaseModel):
    url: HttpUrl
    html: str = Field(min_length=1, max_length=100_000)


class CollectorURLRequest(BaseModel):
    url: HttpUrl


class CollectorCollectURLRequest(CollectorURLRequest):
    save: bool = True


# Query-driven repository search endpoint, separate from the collector test flow.
class CollectorRepositorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class CollectorRepositorySearchItem(BaseModel):
    title: str
    description: str = ""
    url: HttpUrl
    source: str
    publisher: str = ""
    date: str = ""
    doi: str = ""
    keywords: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectorRepositorySearchWarning(BaseModel):
    message: str
    provider: Optional[str] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.


class CollectorRepositorySearchResponse(BaseModel):
    query: str
    items: list[CollectorRepositorySearchItem] = Field(default_factory=list)
    warnings: list[CollectorRepositorySearchWarning] = Field(default_factory=list)


class CollectorDistribution(BaseModel):
    url: str
    format: str
    probability: float
    anchor: str = ""
    mime_type: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_checked_at: str = ""


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
    first_seen_at: str = ""
    last_seen_at: str = ""
    updated_at: str = ""


class CollectorCollectionResponse(BaseModel):
    items: list[CollectorCollectedDataset]
    saved: bool = False
    saved_count: int = 0


class CollectorCollectionJob(BaseModel):
    id: int
    source_url: str
    status: str
    saved_count: int
    discovered_count: int = 0
    analyzed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    invalid_distribution_count: int = 0
    discovery_methods: list[str] = Field(default_factory=list)
    message: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""


class CollectorCollectionJobResponse(BaseModel):
    job: CollectorCollectionJob
