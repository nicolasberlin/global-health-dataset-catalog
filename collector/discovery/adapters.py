from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from collector.config import DEFAULT_CONFIG
from collector.discovery.sitemap import TextFetcher, discover_sitemap_entries
from collector.extraction.distributions import guess_format
from collector.fetch import _ensure_public_http_url
from collector.storage.models import DistributionCandidate
from collector.url_utils import canonicalize_url

JsonFetcher = Callable[[str], dict[str, object]]

EXCLUDED_RESOURCE_FORMATS = {"HTML", "HTM", "PDF", "PNG", "JPG", "JPEG", "GIF", "SVG"}


@dataclass(frozen=True)
class DiscoveredPage:
    url: str
    discovery_method: str
    priority: float = 0.0
    title: str = ""
    description: str = ""
    publisher: str = ""
    distributions: tuple[DistributionCandidate, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class DiscoveryAdapter(Protocol):
    name: str

    def detect(self, source_url: str) -> bool:
        ...

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        ...


class GenericWebsiteAdapter:
    name = "generic_website"

    def __init__(
        self,
        fetch_text: TextFetcher | None = None,
        max_sitemap_urls: int = 50,
    ) -> None:
        self._fetch_text = fetch_text
        self._max_sitemap_urls = max_sitemap_urls

    def detect(self, source_url: str) -> bool:
        return source_url.startswith(("http://", "https://"))

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        sitemap_entries = discover_sitemap_entries(
            source_url,
            fetch_text=self._fetch_text,
            max_urls=self._max_sitemap_urls,
        )
        if sitemap_entries:
            return [
                DiscoveredPage(
                    url=entry.url,
                    discovery_method="sitemap",
                    priority=entry.priority,
                    metadata={
                        **entry.metadata,
                        "source_sitemap_url": entry.source_sitemap_url,
                    },
                )
                for entry in sitemap_entries
            ]

        return [
            DiscoveredPage(
                url=canonicalize_url(source_url),
                discovery_method=self.name,
                priority=0.1,
            )
        ]


class CKANAdapter:
    name = "ckan"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        rows: int = 5,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._rows = rows

    def detect(self, source_url: str) -> bool:
        try:
            data = self._fetch_json(_ckan_action_url(source_url, "status_show"))
        except ValueError:
            return False

        return data.get("success") is True and isinstance(data.get("result"), dict)

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        data = self._fetch_json(
            _ckan_action_url(
                source_url,
                "package_search",
                _ckan_search_params(source_url, self._rows),
            )
        )
        result = data.get("result")
        if data.get("success") is not True or not isinstance(result, dict):
            return []

        packages = result.get("results")
        if not isinstance(packages, list):
            return []

        discovered_pages: list[DiscoveredPage] = []
        for package in packages:
            if not isinstance(package, dict):
                continue

            dataset_url = _dataset_page_url(source_url, package)
            if not dataset_url:
                continue

            distributions = tuple(_distribution_candidates(source_url, package))
            discovered_pages.append(
                DiscoveredPage(
                    url=dataset_url,
                    discovery_method=self.name,
                    priority=0.9 if distributions else 0.75,
                    title=_text(package.get("title")),
                    description=_text(package.get("notes")),
                    publisher=_publisher(package),
                    distributions=distributions,
                    metadata={
                        "ckan_id": _text(package.get("id")),
                        "ckan_name": _text(package.get("name")),
                    },
                )
            )

        return discovered_pages


def fetch_json_url(
    url: str,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_bytes: int = 5_000_000,
) -> dict[str, object]:
    _ensure_public_http_url(url)

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": DEFAULT_CONFIG.user_agent,
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
    except HTTPError as exception:
        raise ValueError(f"JSON URL returned HTTP {exception.code}.") from exception
    except (TimeoutError, URLError, OSError) as exception:
        raise ValueError(f"Could not fetch JSON URL: {exception}") from exception

    if len(body) > max_bytes:
        raise ValueError("JSON response is too large for discovery.")

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exception:
        raise ValueError("JSON URL did not return valid JSON.") from exception

    if not isinstance(data, dict):
        raise ValueError("JSON URL did not return an object.")

    return data


def _ckan_action_url(
    source_url: str,
    action: str,
    params: dict[str, str] | None = None,
) -> str:
    base_url = _ckan_site_root(source_url)
    action_url = urljoin(base_url, f"api/3/action/{action}")
    if not params:
        return action_url

    return f"{action_url}?{urlencode(params)}"


def _ckan_site_root(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _ckan_search_params(source_url: str, rows: int) -> dict[str, str]:
    supported_params = {"q", "fq", "sort"}
    source_params = dict(parse_qsl(urlsplit(source_url).query))
    params = {
        key: value
        for key, value in source_params.items()
        if key in supported_params and value.strip()
    }
    params["rows"] = str(rows)
    return params


def _dataset_page_url(source_url: str, package: dict[object, object]) -> str:
    name = _text(package.get("name"))
    if name:
        return canonicalize_url(f"dataset/{name}", _ckan_site_root(source_url))

    package_id = _text(package.get("id"))
    if package_id:
        return canonicalize_url(f"dataset/{package_id}", _ckan_site_root(source_url))

    return ""


def _distribution_candidates(
    source_url: str,
    package: dict[object, object],
) -> list[DistributionCandidate]:
    resources = package.get("resources")
    if not isinstance(resources, list):
        return []

    distributions: list[DistributionCandidate] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue

        resource_url = _text(resource.get("url"))
        if not resource_url:
            continue

        resource_format = _normalize_format(_text(resource.get("format")))
        mime_type = _text(resource.get("mimetype")) or _text(resource.get("mimetype_inner"))
        anchor = _text(resource.get("name")) or _text(resource.get("description"))
        guessed_format, extension = guess_format(resource_url, anchor=anchor, mime_type=mime_type)
        format_name = resource_format or guessed_format

        if format_name in EXCLUDED_RESOURCE_FORMATS:
            continue

        distributions.append(
            DistributionCandidate(
                url=canonicalize_url(resource_url, source_url),
                format=format_name,
                probability=0.95,
                anchor=anchor,
                extension=extension,
                mime_type=mime_type,
                same_domain=False,
                signals={"ckan_resource": True},
            )
        )

    return distributions


def _publisher(package: dict[object, object]) -> str:
    organization = package.get("organization")
    if not isinstance(organization, dict):
        return ""

    return _text(organization.get("title")) or _text(organization.get("name"))


def _normalize_format(value: str) -> str:
    if not value:
        return ""

    normalized = value.strip().upper()
    if normalized in {"N/A", "NA", "UNKNOWN"}:
        return ""

    return normalized


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


ADAPTERS: tuple[DiscoveryAdapter, ...] = (CKANAdapter(), GenericWebsiteAdapter())
