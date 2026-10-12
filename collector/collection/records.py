"""Platform-independent records before classification or resource validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from collector.storage.models import DistributionCandidate


@dataclass(frozen=True)
class RecordIdentity:
    platform: str
    repository_origin: str
    kind: Literal["dataset", "file"]
    native_id: str = ""
    persistent_id: str = ""
    version: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedRecord:
    """An observation of one record, not an accepted catalogue dataset.

    Resources remain candidates. Parent identifiers never widen file scope.
    The existing DistributionCandidate carries resource identity, access flags
    and format evidence; complete file bodies and raw API payloads are excluded.
    """

    identity: RecordIdentity
    landing_url: str
    metadata_source_url: str
    title: str = ""
    description: str = ""
    publisher: str = ""
    publication_date: str = ""
    license: str = ""
    doi: str = ""
    resources: tuple[DistributionCandidate, ...] = ()
    parent_persistent_id: str = ""

