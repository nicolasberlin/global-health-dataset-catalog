"""Shared collection page, resolution, diagnostics and callback contracts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collector.collection.records import NormalizedRecord
from collector.models import DistributionCandidate, PageSnapshot, ValidationResult
from collector.network.fetch import FetchedPage


@dataclass(frozen=True)
class DiscoveredPage:
    """Normalized page candidate for record connectors and HTML/browser resolution.

    Connector mapping and HTML/browser resolution supply
    this contract to the shared pipeline. ``discovery_method`` identifies the
    origin or resolution method. ``priority`` retains legacy ranking evidence;
    ``distributions`` remain unvalidated candidates. ``discovery_metadata``
    carries optional provenance evidence. The existing public class name
    is retained so caller signatures and field names remain unchanged.
    """

    url: str
    discovery_method: str
    priority: float = 0.0
    title: str = ""
    description: str = ""
    publisher: str = ""
    geography: tuple[str, ...] = ()
    date_of_publication: str = ""
    diseases: tuple[str, ...] = ()
    size_of_dataset: str = ""
    demographic_information: tuple[str, ...] = ()
    sharing_license: str = ""
    modality_of_data: tuple[str, ...] = ()
    distributions: tuple[DistributionCandidate, ...] = ()
    discovery_metadata: dict[str, object] = field(default_factory=dict)
    doi: str = ""
    hosting_platform: str = ""
    record_identity: dict[str, str] = field(default_factory=dict)
    metadata_source_url: str = ""


def public_url(value: str) -> str:
    """Diagnostic URLs retain public identifiers, never session/access credentials."""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host += f":{parsed.port}"
    keep = {"persistentid", "fileid", "version", "format", "id"}
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() in keep]
    path = re.sub(r";jsessionid=[^/?#;]+", ";jsessionid=[redacted]", parsed.path, flags=re.I)
    return urlunsplit((parsed.scheme, host, path, urlencode(query), ""))


@dataclass
class MethodAttempt:
    """Progress and public-safe evidence for one API, HTML or browser attempt."""

    method: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    code: str = ""
    requested_url: str = ""
    final_url: str = ""
    http_status: int | None = None
    resource_count: int = 0
    discovery_coverage: str = "unknown"
    failure_phase: str | None = None
    reason: str | None = None
    service_http_status: int | None = None
    metadata_code: str = ""
    metadata_http_status: int | None = None
    checks: list[dict] = field(default_factory=list)
    request_attempts: int | None = None


@dataclass
class StrategyResult:
    """Unvalidated resolution evidence prepared for the shared collection pipeline.

    ``record`` retains a connector's normalized observation when available;
    HTML/browser results may instead supply page content and a parsed snapshot.
    This is not an accepted catalogue dataset or a persistence payload.
    """

    page: DiscoveredPage
    html: str = ""
    http_status: int | None = None
    final_url: str = ""
    discovery_coverage: str = "unknown"
    resource_count: int = 0
    record: NormalizedRecord | None = None
    metadata_code: str = ""
    metadata_http_status: int | None = None
    snapshot: PageSnapshot | None = None


FetchHTMLFunction = Callable[[str], FetchedPage]
ValidateDistributionFunction = Callable[[DistributionCandidate], ValidationResult]
