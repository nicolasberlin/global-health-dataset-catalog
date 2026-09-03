from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request

from collector.config import DEFAULT_CONFIG
from collector.fetch import open_public_http_url
from collector.url_utils import canonicalize_url, same_domain

TextFetcher = Callable[[str], str]

MAX_SITEMAPS_PER_SOURCE = 10
MAX_URLS_PER_SOURCE = 1_000

POSITIVE_URL_KEYWORDS = {
    "api",
    "catalog",
    "catalogue",
    "csv",
    "data",
    "dataset",
    "datasets",
    "download",
    "downloads",
    "indicator",
    "indicators",
    "json",
    "open-data",
    "resource",
    "resources",
    "statistic",
    "statistics",
    "xlsx",
    "donnees",
    "jeu-de-donnees",
}

NEGATIVE_URL_KEYWORDS = {
    "about",
    "blog",
    "careers",
    "contact",
    "events",
    "jobs",
    "news",
    "press",
    "privacy",
    "terms",
}

URL_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    priority: float
    source_sitemap_url: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedSitemap:
    page_urls: tuple[str, ...] = ()
    nested_sitemap_urls: tuple[str, ...] = ()


def sitemap_urls_from_robots(robots_text: str, source_url: str) -> list[str]:
    sitemap_urls: list[str] = []
    base_url = site_root_url(source_url)

    for line in robots_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sitemap":
            sitemap_url = value.split("#", 1)[0].strip()
            if sitemap_url:
                sitemap_urls.append(canonicalize_url(sitemap_url, base_url))

    return sitemap_urls


def default_sitemap_candidates(source_url: str) -> list[str]:
    base_url = site_root_url(source_url)
    return [
        urljoin(base_url, "robots.txt"),
        urljoin(base_url, "sitemap.xml"),
    ]


def discover_sitemap_entries(
    source_url: str,
    fetch_text: TextFetcher | None = None,
    max_sitemaps: int = MAX_SITEMAPS_PER_SOURCE,
    max_urls: int = MAX_URLS_PER_SOURCE,
) -> list[SitemapEntry]:
    fetch_text = fetch_text or fetch_text_url
    robots_url, default_sitemap_url = default_sitemap_candidates(source_url)
    sitemap_urls = [default_sitemap_url]

    try:
        sitemap_urls = sitemap_urls_from_robots(fetch_text(robots_url), source_url) + sitemap_urls
    except ValueError:
        pass

    entries: list[SitemapEntry] = []
    seen_page_urls: set[str] = set()
    seen_sitemap_urls: set[str] = set()
    pending_sitemap_urls = _dedupe_urls(sitemap_urls)

    while (
        pending_sitemap_urls
        and len(seen_sitemap_urls) < max_sitemaps
        and len(entries) < max_urls
    ):
        sitemap_url = pending_sitemap_urls.pop(0)
        if sitemap_url in seen_sitemap_urls or not same_domain(sitemap_url, source_url):
            continue

        seen_sitemap_urls.add(sitemap_url)

        try:
            parsed_sitemap = parse_sitemap(fetch_text(sitemap_url), sitemap_url)
        except ValueError:
            continue

        for nested_sitemap_url in parsed_sitemap.nested_sitemap_urls:
            nested_sitemap_url = canonicalize_url(nested_sitemap_url, sitemap_url)
            if nested_sitemap_url not in seen_sitemap_urls:
                pending_sitemap_urls.append(nested_sitemap_url)

        for page_url in parsed_sitemap.page_urls:
            page_url = canonicalize_url(page_url, sitemap_url)
            if page_url in seen_page_urls or not same_domain(page_url, source_url):
                continue

            seen_page_urls.add(page_url)
            entries.append(
                SitemapEntry(
                    url=page_url,
                    priority=score_sitemap_url(page_url),
                    source_sitemap_url=sitemap_url,
                    metadata={"source": "sitemap"},
                )
            )

            if len(entries) >= max_urls:
                break

    return sorted(entries, key=lambda entry: (-entry.priority, entry.url))


def parse_sitemap(xml_text: str, sitemap_url: str) -> ParsedSitemap:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exception:
        raise ValueError("Sitemap XML is invalid.") from exception

    root_name = _local_name(root.tag)
    if root_name == "urlset":
        return ParsedSitemap(page_urls=tuple(_loc_values(root, "url", sitemap_url)))

    if root_name == "sitemapindex":
        return ParsedSitemap(nested_sitemap_urls=tuple(_loc_values(root, "sitemap", sitemap_url)))

    raise ValueError("XML document is not a sitemap.")


def score_sitemap_url(url: str) -> float:
    parts = urlsplit(url)
    normalized_text = f"{parts.path} {parts.query}".lower()
    normalized_text = normalized_text.replace("_", "-")
    tokens = set(URL_TOKEN_PATTERN.findall(normalized_text.replace("-", " ")))
    positive_matches = {
        keyword
        for keyword in POSITIVE_URL_KEYWORDS
        if keyword in tokens or keyword in normalized_text
    }
    negative_matches = {
        keyword
        for keyword in NEGATIVE_URL_KEYWORDS
        if keyword in tokens or keyword in normalized_text
    }

    score = 0.2
    score += min(0.55, len(positive_matches) * 0.12)
    if {"dataset", "datasets"} & positive_matches:
        score += 0.15
    if {"download", "downloads", "csv", "xlsx", "json", "api"} & positive_matches:
        score += 0.1
    score -= min(0.35, len(negative_matches) * 0.12)
    if parts.path in {"", "/"}:
        score -= 0.1

    return round(min(max(score, 0.05), 0.95), 3)


def fetch_text_url(
    url: str,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_bytes: int = 5_000_000,
) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/plain,application/xml,text/xml,*/*",
            "User-Agent": DEFAULT_CONFIG.user_agent,
        },
        method="GET",
    )

    try:
        with open_public_http_url(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("Sitemap response is too large for discovery.")
            if urlsplit(response.geturl()).path.endswith(".gz") or "gzip" in content_type:
                body = gzip.decompress(body)
            return _decode_text(body, content_type)
    except HTTPError as exception:
        raise ValueError(f"Sitemap URL returned HTTP {exception.code}.") from exception
    except (TimeoutError, URLError, OSError) as exception:
        raise ValueError(f"Could not fetch sitemap URL: {exception}") from exception


def site_root_url(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _loc_values(root: ET.Element, item_name: str, sitemap_url: str) -> list[str]:
    urls: list[str] = []
    for item in root:
        if _local_name(item.tag) != item_name:
            continue

        loc = _child_text(item, "loc")
        if loc:
            urls.append(canonicalize_url(loc, sitemap_url))

    return urls


def _child_text(element: ET.Element, child_name: str) -> str:
    for child in element:
        if _local_name(child.tag) == child_name and child.text:
            return child.text.strip()

    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url in seen:
            continue

        seen.add(url)
        deduped.append(url)

    return deduped


def _decode_text(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip()
            break

    return body.decode(charset, errors="replace")
