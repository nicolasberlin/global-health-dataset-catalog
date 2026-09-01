from collector.discovery.adapters.ckan import CKANAdapter
from collector.discovery.adapters.html import (
    DataJsonAdapter,
    GenericWebsiteAdapter,
    SocrataAdapter,
)
from collector.discovery.adapters.shared import (
    DiscoveredPage,
    DiscoveryAdapter,
    JsonFetcher,
    fetch_json_url,
)

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
