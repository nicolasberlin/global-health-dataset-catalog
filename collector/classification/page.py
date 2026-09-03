from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from collector.storage.models import DistributionCandidate, PageSnapshot


class PageClassificationError(RuntimeError):
    """Raised when a page classifier cannot produce a usable classification."""


@dataclass(frozen=True)
class PageClassification:
    """Eligibility decision and audit signals for one discovered page."""

    accepted: bool
    dataset_signals: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PageClassificationVote:
    """Page-classification decision attributed to one ensemble voter."""

    voter_id: str
    accepted: bool
    dataset_signals: dict[str, object] = field(default_factory=dict)


class PageClassifier(Protocol):
    """Interface implemented by discovered-page classifiers."""

    def classify(
        self,
        page: PageSnapshot,
        distributions: list[DistributionCandidate],
    ) -> PageClassification:
        ...
