from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonicalize_url(url: str, base_url: str | None = None) -> str:
    absolute_url = urljoin(base_url or "", url.strip())
    parts = urlsplit(absolute_url)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(query_items, doseq=True)
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def normalize_http_url(
    value: str,
    base_url: str | None = None,
) -> str | None:
    if not isinstance(value, str):
        return None
    stripped_value = value.strip()
    if not stripped_value:
        return None
    if "\\" in stripped_value or any(
        character.isspace() or ord(character) == 127 for character in stripped_value
    ):
        return None

    try:
        normalized = canonicalize_url(stripped_value, base_url)
        parts = urlsplit(normalized)
        hostname = parts.hostname
        _ = parts.port
        username = parts.username
        password = parts.password
    except (TypeError, ValueError):
        return None

    if parts.scheme not in {"http", "https"} or not hostname:
        return None
    if username is not None or password is not None:
        return None

    return normalized


def require_http_url(value: str) -> str:
    normalized = normalize_http_url(value)
    if normalized is None:
        raise ValueError("Expected a valid HTTP(S) URL.")
    return normalized


def select_dataset_url(page_url: str, canonical_href: str = "") -> str:
    normalized_page_url = require_http_url(page_url)
    canonical_url = normalize_http_url(canonical_href, normalized_page_url)
    if canonical_url is None:
        return normalized_page_url

    if urlsplit(canonical_url).hostname != urlsplit(normalized_page_url).hostname:
        return normalized_page_url

    return canonical_url


def same_domain(left_url: str, right_url: str) -> bool:
    return urlsplit(left_url).netloc.lower() == urlsplit(right_url).netloc.lower()
