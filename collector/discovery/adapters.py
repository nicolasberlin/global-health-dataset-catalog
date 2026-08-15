from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiscoveredPage:
    url: str
    discovery_method: str
    priority: float = 0.0


class DiscoveryAdapter(Protocol):
    name: str

    def detect(self, source_url: str) -> bool:
        ...

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        ...


class GenericWebsiteAdapter:
    name = "generic_website"

    def detect(self, source_url: str) -> bool:
        return source_url.startswith(("http://", "https://"))

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        return [DiscoveredPage(url=source_url, discovery_method=self.name, priority=0.1)]


ADAPTERS: tuple[DiscoveryAdapter, ...] = (GenericWebsiteAdapter(),)

