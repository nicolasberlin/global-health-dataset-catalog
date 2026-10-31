"""Source-specific adapter and JSON-fetcher contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from collector.collection.contracts import DiscoveredPage

JsonFetcher = Callable[[str], dict[str, object]]


class DiscoveryAdapter(Protocol):
    """Interface for source-specific discovery strategies."""

    name: str

    def detect(self, source_url: str) -> bool:
        ...

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        ...
