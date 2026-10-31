"""Contracts for collection source discovery and its injected JSON fetchers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from collector.storage.models import DistributionCandidate

JsonFetcher = Callable[[str], dict[str, object]]


@dataclass(frozen=True)
class DiscoveredPage:
    """Adapter-normalized candidate emitted at the discovery stage.

    ``discovery_method`` identifies the adapter path. ``priority`` retains
    adapter ranking evidence; adapters may use it when ordering candidates
    before the configured page limit. Structured adapters can attach direct
    ``distributions`` and source-specific ``discovery_metadata``.
    """

    url: str
    discovery_method: str
    priority: float = 0.0
    title: str = ""
    description: str = ""
    publisher: str = ""
    geography: tuple[str, ...] = ()
    date_of_publication: str = ""
    diseases: tuple[str, ...] = ()
    size_of_dataset: str = ""
    demographic_information: tuple[str, ...] = ()
    sharing_license: str = ""
    modality_of_data: tuple[str, ...] = ()
    distributions: tuple[DistributionCandidate, ...] = ()
    discovery_metadata: dict[str, object] = field(default_factory=dict)
    doi: str = ""
    hosting_platform: str = ""
    record_identity: dict[str, str] = field(default_factory=dict)
    metadata_source_url: str = ""


class DiscoveryAdapter(Protocol):
    """Interface for source-specific discovery strategies."""

    name: str

    def detect(self, source_url: str) -> bool:
        ...

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        ...
