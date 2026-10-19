"""Bounded related metadata reads, confined to a connector's configured API."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import unquote, urljoin, urlsplit

from collector.budget import check_collection_budget
from collector.collection.failures import CollectionMetadataError, CollectionResponseError
from collector.collection.http import JsonResponse
from collector.extraction.distributions import guess_format
from collector.storage.models import DistributionCandidate
from collector.url_utils import normalize_http_url


def file_resource(name, url, *, key, mime="", size=None, restricted=False):
    if not name or normalize_http_url(url) is None:
        raise ValueError("Invalid file name or download URL")
    fmt, ext = guess_format(name, mime_type=mime)
    return DistributionCandidate(
        url=url,
        format=fmt,
        extension=ext,
        probability=1.0,
        anchor=name,
        mime_type=mime,
        signals={"resource_key": key, "size_bytes": size, "restricted": restricted},
    )


def known_resources(resources, known_record):
    allowed = {item.url for item in known_record.resources} if known_record else set()
    return [item for item in resources if item.url in allowed]


def api_link(api_root: str, value: str) -> str:
    if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
        raise ValueError("Invalid metadata link")
    target = urljoin(api_root.rstrip("/") + "/", value)
    root, parsed = urlsplit(api_root), urlsplit(target)
    if (
        not value
        or parsed.scheme != "https"
        or parsed.netloc != root.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
        or not parsed.path.startswith(root.path.rstrip("/") + "/")
        or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))
        or "\\" in target
    ):
        raise ValueError("Metadata link leaves the configured API")
    return target


def hal_link(payload: dict, key: str) -> str:
    links = payload.get("_links", {})
    value = links.get(key) if isinstance(links, dict) else None
    href = value.get("href", "") if isinstance(value, dict) else ""
    return href if isinstance(href, str) else ""


class MetadataReader:
    def __init__(self, api_root, fetch_json):
        self.api_root, self.fetch_json = api_root, fetch_json
        self.first = None
        self.requests, self.attempts = 0, 0

    def read(self, url):
        check_collection_budget()
        url = api_link(self.api_root, url)
        if self.requests >= 20:
            raise CollectionResponseError("repository_response_too_large", "decode")
        self.requests += 1
        response = self.fetch_json(url)
        if isinstance(response, JsonResponse):
            # Redirected metadata must not leave the configured API either.
            api_link(self.api_root, response.final_url)
            self.first = self.first or response
            self.attempts += response.request_attempts
            payload = response.payload
        else:
            payload = response
            self.attempts += 1
        if not isinstance(payload, dict):
            raise CollectionMetadataError("repository_metadata_invalid", "normalize")
        return payload

    def response(self, payload):
        return (
            replace(self.first, payload=payload, request_attempts=self.attempts)
            if (self.first is not None)
            else payload
        )

    def listing(self, url, key):
        items, seen, total = [], set(), None
        for _ in range(5):
            url = api_link(self.api_root, url)
            if url in seen:
                raise ValueError("Repeated metadata page")
            seen.add(url)
            payload = self.read(url)
            embedded = payload.get("_embedded")
            page_items = embedded.get(key) if isinstance(embedded, dict) else None
            if not isinstance(page_items, list):
                raise ValueError("Missing embedded file listing")
            items.extend(page_items)
            if len(items) > 10000:
                raise ValueError("File listing is too large")
            page = payload.get("page", {})
            current_total = payload.get(
                "total", page.get("totalElements") if isinstance(page, dict) else None
            )
            if current_total is not None:
                if type(current_total) is not int or current_total < 0:
                    raise ValueError("Invalid listing count")
                if total is not None and current_total != total:
                    raise ValueError("Listing changed during pagination")
                total = current_total
            next_url = hal_link(payload, "next")
            if not next_url:
                if total is not None and total != len(items):
                    raise ValueError("Incomplete file listing")
                return items
            next_url = api_link(self.api_root, next_url)
            if urlsplit(next_url).path != urlsplit(url).path:
                raise ValueError("Pagination changed the resource scope")
            url = next_url
        raise CollectionResponseError("repository_response_too_large", "decode")
