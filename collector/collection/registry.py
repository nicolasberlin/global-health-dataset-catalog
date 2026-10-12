"""Deterministic connector selection with no platform-specific orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from collector.collection.connectors import RecordConnector
from collector.collection.connectors.dataverse import DataverseConnector
from collector.collection.connectors.zenodo import ZenodoConnector
from collector.config import CollectorConfig


@dataclass(frozen=True)
class ConnectorSelection:
    connector: RecordConnector
    api_url: str | None


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[RecordConnector]):
        self.connectors = tuple(connectors)
        names = [connector.name for connector in self.connectors]
        if len(names) != len(set(names)):
            raise ValueError("Connector names must be unique")

    def select(self, url: str) -> ConnectorSelection | None:
        for connector in self.connectors:
            if connector.supports(url):
                return ConnectorSelection(connector, connector.api_url(url))
        return None


def default_registry(config: CollectorConfig) -> ConnectorRegistry:
    return ConnectorRegistry((
        DataverseConnector(config.dataverse_hosts),
        ZenodoConnector(config.zenodo_hosts),
    ))

