from __future__ import annotations

from collector.discovery.adapters import ADAPTERS, DiscoveredPage, DiscoveryAdapter


def discover_source(
    source_url: str,
    adapters: tuple[DiscoveryAdapter, ...] = ADAPTERS,
) -> list[DiscoveredPage]:
    for adapter in adapters:
        if adapter.detect(source_url):
            return adapter.discover(source_url)

    return []

