"""Transport-independent collection observations; never persist raw HTML or cookies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collector.collection.records import NormalizedRecord
from collector.discovery.adapters.shared import DiscoveredPage
from collector.storage.models import PageSnapshot


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
