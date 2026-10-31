"""Select and run the first discovery adapter that recognizes a source."""

from __future__ import annotations

from collector.collection.discovery.adapters import default_adapters
from collector.collection.discovery.models import DiscoveredPage, DiscoveryAdapter
from collector.config import DEFAULT_CONFIG, CollectorConfig


def discover_source(
    source_url: str,
    adapters: tuple[DiscoveryAdapter, ...] | None = None,
    config: CollectorConfig = DEFAULT_CONFIG,
) -> list[DiscoveredPage]:
    """Discover pages with the first adapter that detects ``source_url``."""

    for adapter in default_adapters(config) if adapters is None else adapters:
        if adapter.detect(source_url):
            return adapter.discover(source_url)

    return []
