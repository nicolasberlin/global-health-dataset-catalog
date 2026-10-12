"""Collection connectors resolve one record; repository search stays separate."""

from __future__ import annotations

from typing import Protocol

from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.storage.models import DistributionCandidate


class RecordConnector(Protocol):
    name: str
    method: str

    def supports(self, url: str) -> bool:
        """Recognize record scope even when only HTML resolution is supported."""
        ...

    def api_url(self, url: str) -> str | None:
        """Recognize a supported URL locally, without any network calls."""
        ...

    def reference_identity(self, url: str) -> RecordIdentity:
        """Identity established by the reference, without inventing API metadata."""
        ...

    def normalize(self, url: str, payload: dict | list) -> NormalizedRecord:
        """Validate the response and preserve the requested record scope."""
        ...

    def scope_resources(
        self, url: str, resources: list[DistributionCandidate],
        known_record: NormalizedRecord | None = None,
    ) -> list[DistributionCandidate]:
        """Restrict fallback links to the original file when resolving a file URL."""
        ...

