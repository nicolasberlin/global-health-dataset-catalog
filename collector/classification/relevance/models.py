"""Repository-result relevance contracts and validation rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from collector.models import PageSnapshot

RepositoryRelevanceLabel = Literal[
    "relevant",
    "somewhat_relevant",
    "not_relevant",
    "insufficient_information",
]

REPOSITORY_RELEVANCE_LABELS: set[RepositoryRelevanceLabel] = {
    "relevant",
    "somewhat_relevant",
    "not_relevant",
    "insufficient_information",
}
# Partially relevant results remain eligible for the repository search flow.
REPOSITORY_ACCEPTED_RELEVANCE_LABELS: set[RepositoryRelevanceLabel] = {
    "relevant",
    "somewhat_relevant",
}

# Bound structured classification output independently of candidate input limits.
MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS = 2_000
MAX_REPOSITORY_MISSING_INFORMATION_ITEMS = 20
MAX_REPOSITORY_MISSING_INFORMATION_CHARS = 500


@dataclass(frozen=True)
class RepositoryClassification:
    """Validated relevance decision attached to a repository search result.

    ``accepted`` is derived from ``relevance_label`` and controls result
    eligibility in the repository flow. ``missing_information`` is valid only
    for an insufficient-information decision, while ``ensemble`` preserves the
    aggregate vote audit trail.
    """

    relevance_label: RepositoryRelevanceLabel
    reason: str
    missing_information: list[str] = field(default_factory=list)
    ensemble: dict[str, object] = field(default_factory=dict)
    accepted: bool = field(init=False)

    def __post_init__(self) -> None:
        _validate_relevance_label(self.relevance_label)
        reason = self.reason.strip()
        if not reason:
            raise ValueError("Repository classification reason cannot be empty.")

        missing_information = _normalized_missing_information(
            self.relevance_label,
            self.missing_information,
        )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "missing_information", missing_information)
        object.__setattr__(
            self,
            "accepted",
            self.relevance_label in REPOSITORY_ACCEPTED_RELEVANCE_LABELS,
        )


@dataclass(frozen=True)
class RepositoryClassificationVote:
    """One model's repository-relevance decision before vote aggregation.

    ``accepted`` is derived from the voter's relevance label. ``voter_id``
    identifies the model for auditing, and ``missing_information`` follows the
    same insufficient-information invariant as the final decision.
    """

    voter_id: str
    relevance_label: RepositoryRelevanceLabel
    reason: str
    missing_information: list[str] = field(default_factory=list)
    accepted: bool = field(init=False)

    def __post_init__(self) -> None:
        _validate_relevance_label(self.relevance_label)
        reason = self.reason.strip()
        if not reason:
            raise ValueError("Repository classification vote reason cannot be empty.")

        missing_information = _normalized_missing_information(
            self.relevance_label,
            self.missing_information,
        )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "missing_information", missing_information)
        object.__setattr__(
            self,
            "accepted",
            self.relevance_label in REPOSITORY_ACCEPTED_RELEVANCE_LABELS,
        )


class RepositoryResultClassifier(Protocol):
    """Interface implemented by repository-result classifiers."""

    def classify(self, page: PageSnapshot) -> RepositoryClassification:
        ...


def _validate_relevance_label(value: object) -> None:
    if not isinstance(value, str) or value not in REPOSITORY_RELEVANCE_LABELS:
        raise ValueError(f"Unsupported repository relevance label: {value!r}.")


def _normalized_missing_information(
    relevance_label: RepositoryRelevanceLabel,
    values: list[str],
) -> list[str]:
    normalized_values = list(
        dict.fromkeys(value.strip() for value in values if value.strip())
    )
    if relevance_label == "insufficient_information":
        if not normalized_values:
            raise ValueError(
                "An insufficient-information classification must identify missing "
                "information in missing_information."
            )
        return normalized_values

    if normalized_values:
        raise ValueError(
            "missing_information must be empty unless the classification "
            "label is insufficient_information."
        )

    return []
