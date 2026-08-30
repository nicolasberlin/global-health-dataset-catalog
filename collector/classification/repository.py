from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from collector.storage.models import PageSnapshot

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
REPOSITORY_ACCEPTED_RELEVANCE_LABELS: set[RepositoryRelevanceLabel] = {
    "relevant",
    "somewhat_relevant",
}

MAX_REPOSITORY_TITLE_CHARS = 500
MAX_REPOSITORY_SEARCH_QUERY_CHARS = 300
MAX_REPOSITORY_DESCRIPTION_CHARS = 20_000
MAX_REPOSITORY_SOURCE_CHARS = 100
MAX_REPOSITORY_PUBLISHER_CHARS = 500
MAX_REPOSITORY_DATE_CHARS = 100
MAX_REPOSITORY_DOI_CHARS = 500
MAX_REPOSITORY_KEYWORDS = 100
MAX_REPOSITORY_KEYWORD_CHARS = 200
MAX_REPOSITORY_METADATA_BYTES = 100_000
MAX_REPOSITORY_METADATA_VALUE_CHARS = 2_000
MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS = 10_000
MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS = 2_000
MAX_REPOSITORY_MISSING_INFORMATION_ITEMS = 20
MAX_REPOSITORY_MISSING_INFORMATION_CHARS = 500


@dataclass(frozen=True)
class RepositoryClassification:
    relevance_label: RepositoryRelevanceLabel
    reason: str
    missing_information: list[str] = field(default_factory=list)
    ensemble: dict[str, object] = field(default_factory=dict)
    accepted: bool = field(init=False)

    def __post_init__(self) -> None:
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
    voter_id: str
    relevance_label: RepositoryRelevanceLabel
    reason: str
    missing_information: list[str] = field(default_factory=list)
    accepted: bool = field(init=False)

    def __post_init__(self) -> None:
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
    def classify(self, page: PageSnapshot) -> RepositoryClassification:
        ...


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
                "An insufficient-information classification must identify missing information."
            )
        return normalized_values

    return []
