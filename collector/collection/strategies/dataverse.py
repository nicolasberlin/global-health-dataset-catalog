"""Compatibility entry points for the Dataverse connector."""

from __future__ import annotations

from urllib.parse import urlsplit

from collector.collection.connectors.dataverse import DataverseConnector
from collector.collection.contracts import StrategyResult
from collector.collection.record_mapping import to_strategy_result


def record_api_url(url: str, hosts: tuple[str, ...]) -> str | None:
    return DataverseConnector(hosts).api_url(url)


def resolve_metadata(url: str, payload: dict | list) -> StrategyResult:
    connector = DataverseConnector((urlsplit(url).hostname,))
    return to_strategy_result(connector.normalize(url, payload), connector.method)
