"""Catalogue dataset, distribution and validation response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class CollectorDistribution(BaseModel):
    url: str
    format: str
    probability: float
    anchor: str = ""
    mime_type: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_checked_at: str = ""


class CollectorValidation(BaseModel):
    url: str
    final_url: str
    format: str
    ok: bool
    status: Literal["available", "restricted", "unavailable", "unconfirmed"] = "unconfirmed"
    reason: str = ""
    http_status: int | None
    mime_type: str = ""
    size_bytes: int | None = None
    etag: str = ""
    last_modified: str = ""
    content_disposition: str = ""
    error: str = ""
    error_code: Literal["", "validation_failed"] = ""


class CollectorCollectedDataset(BaseModel):
    """A full saved dataset record returned by catalogue reads, including download links."""

    id: int | None = None
    source_url: str = ""
    dataset_url: HttpUrl
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    geography: list[str] = Field(default_factory=list)
    date_of_publication: str = ""
    sharing_license: str = ""
    doi: str = ""
    metadata_provenance: dict[str, Any] = Field(default_factory=dict)
    record_identity: dict[str, str] = Field(default_factory=dict)
    discovery_method: str
    dataset_signals: dict[str, Any]
    distributions: list[CollectorDistribution]
    validation_results: list[CollectorValidation]
    first_seen_at: str = ""
    last_seen_at: str = ""
    updated_at: str = ""


class CollectorCollectionResponse(BaseModel):
    """Dataset records returned by a catalogue read; next_cursor supports paged clients."""

    next_cursor: int | None = None
    items: list[CollectorCollectedDataset]
