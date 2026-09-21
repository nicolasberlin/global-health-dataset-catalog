"""Discovery adapter registry and public adapter contracts."""

from collector.discovery.adapters.ckan import CKANAdapter
from collector.discovery.adapters.data_json import DataJsonAdapter
from collector.discovery.adapters.generic import GenericWebsiteAdapter
from collector.discovery.adapters.shared import (
    DiscoveredPage,
    DiscoveryAdapter,
    JsonFetcher,
    fetch_json_url,
)
from collector.discovery.adapters.socrata import SocrataAdapter

# Detection stops at the first match, so the generic HTTP adapter must remain last.
ADAPTERS: tuple[DiscoveryAdapter, ...] = (
    CKANAdapter(),
    SocrataAdapter(),
    DataJsonAdapter(),
    GenericWebsiteAdapter(),
)

__all__ = [
    "ADAPTERS",
    "CKANAdapter",
    "DataJsonAdapter",
    "DiscoveredPage",
    "DiscoveryAdapter",
    "GenericWebsiteAdapter",
    "JsonFetcher",
    "SocrataAdapter",
    "fetch_json_url",
]
