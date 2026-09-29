"""Discovery adapter registry and public adapter contracts."""

from functools import partial

from collector.config import DEFAULT_CONFIG, CollectorConfig
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
from collector.discovery.sitemap import fetch_text_url


def default_adapters(config: CollectorConfig = DEFAULT_CONFIG) -> tuple[DiscoveryAdapter, ...]:
    """Bind detection and discovery requests to one run without mutating shared adapters.

    Catalog/sitemap response limits remain independent of validation sample size.
    """
    fetch_json = partial(
        fetch_json_url, timeout=config.request_timeout_seconds, user_agent=config.user_agent,
    )
    fetch_text = partial(
        fetch_text_url, timeout=config.request_timeout_seconds, user_agent=config.user_agent,
    )
    # Detection stops at the first match, so the generic HTTP adapter must remain last.
    return (
        CKANAdapter(fetch_json=fetch_json),
        SocrataAdapter(fetch_json=fetch_json),
        DataJsonAdapter(fetch_json=fetch_json),
        GenericWebsiteAdapter(fetch_text=fetch_text),
    )


ADAPTERS: tuple[DiscoveryAdapter, ...] = default_adapters()

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
    "default_adapters",
]
