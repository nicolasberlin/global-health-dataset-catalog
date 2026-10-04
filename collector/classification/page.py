from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from collector.diagnostics import Diagnostic, PipelineFailure
from collector.storage.models import DistributionCandidate, PageSnapshot


class PageClassificationError(PipelineFailure):
    """Raised when a page classifier cannot produce a usable classification."""

    def __init__(
        self,
        message: str,
        *,
        code="processing_failed",
        recovery="manual",
        retry_at=None,
        diagnostics=None,
    ):
        super().__init__(
            message,
            diagnostics=diagnostics
            or [
                Diagnostic(code, "classification", recovery=recovery, retry_at=retry_at),
            ],
        )


@dataclass(frozen=True)
class PageClassification:
    """Validated page-eligibility decision produced before distribution validation.

    ``accepted`` controls whether collection continues. ``dataset_signals``
    preserves the decision evidence, including ensemble audit data when an
    ensemble performs the classification.
    """

    accepted: bool
    dataset_signals: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PageClassificationVote:
    """One classifier's page-eligibility decision before vote aggregation.

    ``voter_id`` identifies the model in the audit trail, and
    ``dataset_signals`` contains that voter's evidence rather than the final
    ensemble summary.
    """

    voter_id: str
    accepted: bool
    dataset_signals: dict[str, object] = field(default_factory=dict)


class PageClassifier(Protocol):
    """Interface implemented by discovered-page classifiers."""

    def classify(
        self,
        page: PageSnapshot,
        distributions: list[DistributionCandidate],
    ) -> PageClassification: ...
