from __future__ import annotations

from urllib.parse import urljoin


def sitemap_urls_from_robots(robots_text: str, source_url: str) -> list[str]:
    sitemap_urls: list[str] = []

    for line in robots_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sitemap":
            sitemap_url = value.strip()
            if sitemap_url:
                sitemap_urls.append(urljoin(source_url, sitemap_url))

    return sitemap_urls


def default_sitemap_candidates(source_url: str) -> list[str]:
    return [
        urljoin(source_url.rstrip("/") + "/", "robots.txt"),
        urljoin(source_url.rstrip("/") + "/", "sitemap.xml"),
    ]

