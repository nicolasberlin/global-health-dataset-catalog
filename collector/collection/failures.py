"""Controlled collection failures; provider exception text stays out of traces."""

from __future__ import annotations

from collector.network.fetch import PageFetchError

FAILURE_PHASES = {"fetch", "decode", "normalize", "render", "validate", "classify", "access"}


class CollectionStepError(PageFetchError):
    def __init__(
        self,
        code: str,
        phase: str,
        *,
        http_status: int | None = None,
        final_url: str = "",
        service_http_status: int | None = None,
    ):
        super().__init__("Collection step failed.", code=code)
        self.phase = phase
        self.http_status = http_status
        self.final_url = final_url
        self.service_http_status = service_http_status


class CollectionTransportError(CollectionStepError):
    """A remote HTTP request failed or could not be completed."""


class CollectionResponseError(CollectionStepError):
    """A received response could not be decoded safely."""


class CollectionMetadataError(CollectionStepError):
    """Readable metadata does not satisfy the selected connector contract."""
