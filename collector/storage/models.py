from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

HealthLabel = Literal["HEALTH", "PARTIALLY_HEALTH", "NON_HEALTH"]


@dataclass(frozen=True)
class LinkCandidate:
    url: str
    anchor: str = ""
    nearby_text: str = ""
    extension: str = ""
    same_domain: bool = False
    dom_path: str = ""


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    canonical_url: str
    title: str = ""
    h1: str = ""
    meta_description: str = ""
    og_title: str = ""
    og_description: str = ""
    headings: tuple[str, ...] = ()
    text: str = ""
    publisher: str = ""
    hosting_platform: str = ""
    uploader: str = ""
    links: tuple[LinkCandidate, ...] = ()
    json_ld: tuple[object, ...] = ()


@dataclass(frozen=True)
class ClassificationResult:
    probability: float
    signals: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthClassification:
    probability: float
    label: HealthLabel
    signals: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DistributionCandidate:
    url: str
    format: str
    probability: float
    anchor: str = ""
    extension: str = ""
    mime_type: str = ""
    nearby_text: str = ""
    same_domain: bool = False
    dom_path: str = ""
    signals: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class HTTPProbe:
    url: str
    final_url: str
    status_code: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body_sample: bytes = b""
    error: str = ""


@dataclass(frozen=True)
class ValidationResult:
    url: str
    final_url: str
    format: str
    ok: bool
    http_status: int | None
    mime_type: str = ""
    size_bytes: int | None = None
    etag: str = ""
    last_modified: str = ""
    content_disposition: str = ""
    error: str = ""


@dataclass(frozen=True)
class CollectedDataset:
    dataset_url: str
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    dataset_probability: float
    dataset_signals: dict[str, object]
    health_probability: float
    health_label: HealthLabel
    health_signals: dict[str, object]
    distributions: list[DistributionCandidate] = field(default_factory=list)
