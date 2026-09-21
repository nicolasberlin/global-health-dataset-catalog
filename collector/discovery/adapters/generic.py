"""Generic website discovery through sitemaps and source-page fallback."""

from __future__ import annotations

from collector.discovery.adapters.shared import DiscoveredPage
from collector.discovery.sitemap import TextFetcher, discover_sitemap_entries
from collector.url_utils import canonicalize_url


class GenericWebsiteAdapter:
    """Discover same-domain sitemap pages, falling back to the source page."""

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
                    discovery_metadata={
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
