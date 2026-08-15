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


def same_domain(left_url: str, right_url: str) -> bool:
    return urlsplit(left_url).netloc.lower() == urlsplit(right_url).netloc.lower()

