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


@dataclass(frozen=True)
class SocrataCatalogResult:
    resource: dict[object, object]
    metadata: dict[object, object]
    permalink: str = ""
    link: str = ""


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


class SocrataAdapter:
    name = "socrata"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        rows: int = 5,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._rows = rows

    def detect(self, source_url: str) -> bool:
        try:
            data = self._fetch_json(
                _socrata_catalog_url(source_url, rows=1, include_source_query=False)
            )
        except ValueError:
            return False

        return bool(_socrata_results(data, source_url))

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        data = self._fetch_json(
            _socrata_catalog_url(source_url, rows=self._rows, include_source_query=True)
        )

        discovered_pages: list[DiscoveredPage] = []
        for result in _socrata_results(data, source_url):
            resource = result.resource
            socrata_id = _text(resource.get("id"))
            if not socrata_id:
                continue

            dataset_url = _socrata_dataset_url(source_url, result)
            if not dataset_url:
                continue

            distributions = tuple(_socrata_distribution_candidates(source_url, socrata_id))
            discovered_pages.append(
                DiscoveredPage(
                    url=dataset_url,
                    discovery_method=self.name,
                    priority=0.9,
                    title=_text(resource.get("name")),
                    description=_text(resource.get("description")),
                    publisher=_text(resource.get("attribution")),
                    distributions=distributions,
                    metadata={
                        "socrata_id": socrata_id,
                        "socrata_type": _text(resource.get("type")),
                        "socrata_domain": _socrata_domain(source_url),
                    },
                )
            )

        return discovered_pages


class DataJsonAdapter:
    name = "data_json"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        rows: int = 5,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._rows = rows

    def detect(self, source_url: str) -> bool:
        try:
            data = self._fetch_json(_data_json_url(source_url))
        except ValueError:
            return False

        return bool(_data_json_datasets(data))

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        data_json_url = _data_json_url(source_url)
        data = self._fetch_json(data_json_url)
        query = _source_query(source_url)
        discovered_pages: list[DiscoveredPage] = []

        for dataset in _data_json_datasets(data):
            if query and not _data_json_dataset_matches_query(dataset, query):
                continue

            dataset_url = _data_json_dataset_url(source_url, data_json_url, dataset)
            if not dataset_url:
                continue

            distributions = tuple(_data_json_distribution_candidates(source_url, dataset))
            discovered_pages.append(
                DiscoveredPage(
                    url=dataset_url,
                    discovery_method=self.name,
                    priority=0.9 if distributions else 0.75,
                    title=_first_text(dataset, "title", "dct:title", "name"),
                    description=_first_text(dataset, "description", "dct:description"),
                    publisher=_data_json_publisher(dataset),
                    distributions=distributions,
                    metadata={
                        "data_json_url": data_json_url,
                        "identifier": _first_text(dataset, "identifier", "@id"),
                        "keywords": _text_values(dataset.get("keyword")),
                    },
                )
            )

            if len(discovered_pages) >= self._rows:
                break

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


def _socrata_catalog_url(
    source_url: str,
    rows: int,
    include_source_query: bool,
) -> str:
    domain = _socrata_domain(source_url)
    params = {
        "domains": domain,
        "search_context": domain,
        "limit": str(rows),
    }
    if include_source_query:
        source_params = dict(parse_qsl(urlsplit(source_url).query))
        query = _text(source_params.get("q"))
        if query:
            params["q"] = query

    return f"https://api.us.socrata.com/api/catalog/v1?{urlencode(params)}"


def _socrata_domain(source_url: str) -> str:
    return urlsplit(source_url).netloc.lower()


def _socrata_results(
    data: dict[str, object],
    source_url: str,
) -> list[SocrataCatalogResult]:
    results = data.get("results")
    if not isinstance(results, list):
        return []

    source_domain = _socrata_domain(source_url)
    socrata_results: list[SocrataCatalogResult] = []
    for result in results:
        if not isinstance(result, dict):
            continue

        resource = result.get("resource")
        if not isinstance(resource, dict):
            continue

        metadata = result.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        result_domain = _text(metadata.get("domain")) or _text(resource.get("domain"))
        if result_domain and result_domain.lower() != source_domain:
            continue

        resource_type = _text(resource.get("type")).lower()
        if resource_type and resource_type not in {"dataset", "file"}:
            continue

        socrata_results.append(
            SocrataCatalogResult(
                resource=resource,
                metadata=metadata,
                permalink=_text(result.get("permalink")),
                link=_text(result.get("link")),
            )
        )

    return socrata_results


def _socrata_dataset_url(
    source_url: str,
    result: SocrataCatalogResult,
) -> str:
    if result.permalink:
        return canonicalize_url(result.permalink, _socrata_site_root(source_url))
    if result.link:
        return canonicalize_url(result.link, _socrata_site_root(source_url))

    resource = result.resource
    metadata = result.metadata
    for key in ("permalink", "link", "webUri", "web_uri"):
        resource_url = _text(resource.get(key)) or _text(metadata.get(key))
        if resource_url:
            return canonicalize_url(resource_url, _socrata_site_root(source_url))

    socrata_id = _text(resource.get("id"))
    if not socrata_id:
        return ""

    return canonicalize_url(f"d/{socrata_id}", _socrata_site_root(source_url))


def _socrata_distribution_candidates(
    source_url: str,
    socrata_id: str,
) -> list[DistributionCandidate]:
    site_root = _socrata_site_root(source_url)
    csv_url = canonicalize_url(f"resource/{socrata_id}.csv", site_root)
    json_url = canonicalize_url(f"resource/{socrata_id}.json", site_root)
    api_url = canonicalize_url(
        f"resource/{socrata_id}.json?{urlencode({'$limit': '1'})}",
        site_root,
    )

    return [
        DistributionCandidate(
            url=csv_url,
            format="CSV",
            probability=0.95,
            anchor="Socrata CSV export",
            extension=".csv",
            mime_type="text/csv",
            same_domain=True,
            signals={"socrata_resource": True},
        ),
        DistributionCandidate(
            url=json_url,
            format="JSON",
            probability=0.9,
            anchor="Socrata JSON export",
            extension=".json",
            mime_type="application/json",
            same_domain=True,
            signals={"socrata_resource": True},
        ),
        DistributionCandidate(
            url=api_url,
            format="API",
            probability=0.85,
            anchor="Socrata SODA API",
            extension=".json",
            mime_type="application/json",
            same_domain=True,
            signals={"socrata_resource": True, "api_endpoint": True},
        ),
    ]


def _socrata_site_root(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _data_json_url(source_url: str) -> str:
    parts = urlsplit(source_url)
    if parts.path.rstrip("/").endswith("/data.json") or parts.path == "/data.json":
        return canonicalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))

    return canonicalize_url("data.json", _site_root(source_url))


def _data_json_datasets(data: dict[str, object]) -> list[dict[object, object]]:
    datasets = data.get("dataset")
    if isinstance(datasets, list):
        return [dataset for dataset in datasets if isinstance(dataset, dict)]

    graph = data.get("@graph")
    if isinstance(graph, list):
        return [
            item
            for item in graph
            if isinstance(item, dict) and _json_ld_type_matches(item.get("@type"), "Dataset")
        ]

    return []


def _data_json_dataset_url(
    source_url: str,
    data_json_url: str,
    dataset: dict[object, object],
) -> str:
    for key in ("landingPage", "dcat:landingPage", "accessURL", "dcat:accessURL", "@id"):
        value = _first_url(dataset.get(key))
        if value:
            return canonicalize_url(value, _site_root(source_url))

    identifier = _first_text(dataset, "identifier")
    if identifier:
        return f"{data_json_url}?{urlencode({'identifier': identifier})}"

    return data_json_url


def _data_json_distribution_candidates(
    source_url: str,
    dataset: dict[object, object],
) -> list[DistributionCandidate]:
    distributions = dataset.get("distribution") or dataset.get("dcat:distribution")
    if isinstance(distributions, dict):
        distribution_items = [distributions]
    elif isinstance(distributions, list):
        distribution_items = [
            distribution
            for distribution in distributions
            if isinstance(distribution, dict)
        ]
    else:
        distribution_items = []

    candidates: list[DistributionCandidate] = []
    for distribution in distribution_items:
        download_url = _first_url(
            distribution.get("downloadURL"),
            distribution.get("dcat:downloadURL"),
        )
        access_url = _first_url(
            distribution.get("accessURL"),
            distribution.get("dcat:accessURL"),
        )
        resource_url = download_url or access_url
        if not resource_url:
            continue

        title = _first_text(distribution, "title", "dct:title", "name")
        description = _first_text(distribution, "description", "dct:description")
        media_type = _first_text(distribution, "mediaType", "dcat:mediaType")
        format_text = _first_text(distribution, "format", "dct:format")
        effective_mime_type = media_type or (format_text if "/" in format_text else "")
        anchor = title or description
        format_name, extension = _data_json_format(
            resource_url,
            format_text,
            effective_mime_type,
            anchor,
            has_download_url=bool(download_url),
        )

        if format_name in EXCLUDED_RESOURCE_FORMATS:
            continue

        candidates.append(
            DistributionCandidate(
                url=canonicalize_url(resource_url, source_url),
                format=format_name,
                probability=0.95 if download_url else 0.75,
                anchor=anchor,
                extension=extension,
                mime_type=effective_mime_type,
                same_domain=urlsplit(resource_url).netloc.lower()
                == urlsplit(source_url).netloc.lower(),
                signals={
                    "data_json_distribution": True,
                    "download_url": bool(download_url),
                    "access_url": bool(access_url),
                },
            )
        )

    return candidates


def _data_json_format(
    resource_url: str,
    format_text: str,
    media_type: str,
    anchor: str,
    has_download_url: bool,
) -> tuple[str, str]:
    guessed_format, extension = guess_format(resource_url, anchor=anchor, mime_type=media_type)
    if format_text and "/" not in format_text:
        normalized_format = _normalize_format(format_text)
        if normalized_format and normalized_format not in {"DATA", "FILE"}:
            return normalized_format, extension

    if guessed_format != "UNKNOWN":
        return guessed_format, extension

    return ("UNKNOWN" if has_download_url else "API"), extension


def _data_json_publisher(dataset: dict[object, object]) -> str:
    publisher = dataset.get("publisher") or dataset.get("dct:publisher")
    if isinstance(publisher, dict):
        return _first_text(publisher, "name", "title", "foaf:name", "dct:title")

    return _first_text_value(publisher)


def _data_json_dataset_matches_query(dataset: dict[object, object], query: str) -> bool:
    searchable_text = " ".join(
        [
            _first_text(dataset, "title", "dct:title", "name"),
            _first_text(dataset, "description", "dct:description"),
            _data_json_publisher(dataset),
            " ".join(_text_values(dataset.get("keyword"))),
            " ".join(_text_values(dataset.get("theme"))),
        ]
    ).lower()
    return query.lower() in searchable_text


def _source_query(source_url: str) -> str:
    return _text(dict(parse_qsl(urlsplit(source_url).query)).get("q"))


def _first_text(mapping: dict[object, object], *keys: str) -> str:
    for key in keys:
        value = _first_text_value(mapping.get(key))
        if value:
            return value

    return ""


def _first_text_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _first_text(value, "@value", "value", "name", "title")
    if isinstance(value, list):
        for item in value:
            text = _first_text_value(item)
            if text:
                return text

    return ""


def _text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        text = _first_text_value(value)
        return [text] if text else []
    if isinstance(value, list):
        return [
            text
            for item in value
            for text in [_first_text_value(item)]
            if text
        ]

    return []


def _first_url(*values: object) -> str:
    for value in values:
        text = _first_text_value(value)
        if text:
            return text

    return ""


def _json_ld_type_matches(value: object, expected_type: str) -> bool:
    return any(
        item.rsplit(":", 1)[-1].lower() == expected_type.lower()
        for item in _text_values(value)
    )


def _site_root(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


ADAPTERS: tuple[DiscoveryAdapter, ...] = (
    CKANAdapter(),
    SocrataAdapter(),
    DataJsonAdapter(),
    GenericWebsiteAdapter(),
)
