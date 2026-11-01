"""Aggregate repository relevance votes and resolve relevance-label ties."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from collector.classification.relevance.models import (
    RepositoryClassification,
    RepositoryClassificationVote,
    RepositoryRelevanceLabel,
    RepositoryResultClassifier,
)
from collector.llm.errors import ClassificationError
from collector.llm.voting import VotingEnsemble
from collector.storage.models import PageSnapshot

# Ties are resolved by selecting the first matching, most conservative label.
REPOSITORY_RELEVANCE_CONSERVATIVE_ORDER: tuple[RepositoryRelevanceLabel, ...] = (
    "not_relevant",
    "insufficient_information",
    "somewhat_relevant",
    "relevant",
)



class EnsembleRepositoryRelevanceClassifier:
    """Run repository classifiers in parallel and combine relevance votes.

    Classification fails when fewer than ``minimum_successful_votes`` voters
    return usable decisions.
    """

    def __init__(
        self,
        voters: (
            list[tuple[str, RepositoryResultClassifier]]
            | tuple[tuple[str, RepositoryResultClassifier], ...]
        ),
        votes_required: int = 2,
        minimum_successful_votes: int | None = None,
    ) -> None:
        self._voting = VotingEnsemble(
            voters,
            minimum_accept_votes=votes_required,
            minimum_successful_votes=minimum_successful_votes,
            name="EnsembleRepositoryRelevanceClassifier",
        )

    @property
    def voter_ids(self) -> tuple[str, ...]:
        return self._voting.voter_ids

    @property
    def votes_required(self) -> int:
        return self._voting.minimum_accept_votes

    @property
    def minimum_successful_votes(self) -> int:
        return self._voting.minimum_successful_votes

    def classify(
        self,
        page: PageSnapshot,
    ) -> RepositoryClassification:
        voting_result = self._voting.evaluate(
            classify=lambda classifier: classifier.classify(page),
            make_vote=_to_repository_relevance_vote,
            handled_errors=(ClassificationError, ValueError),
        )
        # Only votes supporting acceptance/rejection participate in label selection.
        supporting_votes = voting_result.supporting_votes
        if not supporting_votes:
            raise ClassificationError(
                "No repository classifier vote supports the ensemble decision."
            )
        relevance_label = _majority_relevance_label(supporting_votes)

        return RepositoryClassification(
            relevance_label=relevance_label,
            reason=_relevance_reason(supporting_votes, relevance_label),
            missing_information=_combined_missing_information(supporting_votes, relevance_label),
            ensemble=voting_result.to_summary(_repository_vote_summary),
        )


def _to_repository_relevance_vote(
    voter_id: str,
    classification: RepositoryClassification,
) -> RepositoryClassificationVote:
    return RepositoryClassificationVote(
        voter_id=voter_id,
        relevance_label=classification.relevance_label,
        reason=classification.reason,
        missing_information=list(classification.missing_information),
    )


def _repository_vote_summary(
    vote: RepositoryClassificationVote,
) -> dict[str, object]:
    return {
        "voter_id": vote.voter_id,
        "accepted": vote.accepted,
        "relevance_label": vote.relevance_label,
        "reason": vote.reason,
        "missing_information": vote.missing_information,
    }


def _majority_relevance_label(
    votes: Iterable[RepositoryClassificationVote],
) -> RepositoryRelevanceLabel:
    counts = Counter(
        vote.relevance_label
        for vote in votes
    )

    max_count = max(counts.values())

    tied_labels = {
        label
        for label, count in counts.items()
        if count == max_count
    }

    for label in REPOSITORY_RELEVANCE_CONSERVATIVE_ORDER:
        if label in tied_labels:
            return label

    raise ClassificationError(
        "Classifier votes did not include a relevance label."
    )


def _relevance_reason(
    votes: Iterable[RepositoryClassificationVote],
    relevance_label: RepositoryRelevanceLabel,
) -> str:
    return next(
        (
            vote.reason
            for vote in votes
            if (
                vote.relevance_label == relevance_label
                and vote.reason
            )
        ),
        "",
    )


def _combined_missing_information(
    votes: Iterable[RepositoryClassificationVote],
    relevance_label: RepositoryRelevanceLabel,
) -> list[str]:
    if relevance_label != "insufficient_information":
        return []

    missing_information: list[str] = []

    for vote in votes:
        for item in vote.missing_information:
            if item not in missing_information:
                missing_information.append(item)

    return missing_information
