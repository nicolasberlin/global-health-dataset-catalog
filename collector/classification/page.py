from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from collector.storage.models import DistributionCandidate, PageSnapshot


class PageClassificationError(RuntimeError):
    """Raised when a page classifier cannot produce a usable classification."""


@dataclass(frozen=True)
class PageClassification:
    accepted: bool
    dataset_signals: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PageClassificationVote:
    voter_id: str
    accepted: bool
    dataset_signals: dict[str, object] = field(default_factory=dict)


class PageClassifier(Protocol):
    def classify(
        self,
        page: PageSnapshot,
        distributions: list[DistributionCandidate],
    ) -> PageClassification:
        ...
