"""Aggregate repository relevance votes and resolve relevance-label ties."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from collector.classification.errors import PageClassificationError
from collector.classification.relevance.models import (
    RepositoryClassification,
    RepositoryClassificationVote,
    RepositoryRelevanceLabel,
    RepositoryResultClassifier,
)
from collector.classification.voting import (
    _ensemble_summary,
    _minimum_votes_error,
    _validate_voting_thresholds,
    run_voters,
)
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
        if not voters:
            raise ValueError(
                "EnsembleRepositoryRelevanceClassifier requires at least one voter."
            )

        voter_ids = [voter_id for voter_id, _classifier in voters]

        if len(set(voter_ids)) != len(voter_ids):
            raise ValueError(
                "EnsembleRepositoryRelevanceClassifier voter ids must be unique."
            )

        self._voters = tuple(voters)
        self._votes_required = votes_required
        self._minimum_successful_votes = _validate_voting_thresholds(
            voter_count=len(self._voters),
            votes_required=votes_required,
            minimum_successful_votes=minimum_successful_votes,
        )

    @property
    def voter_ids(self) -> tuple[str, ...]:
        return tuple(voter_id for voter_id, _classifier in self._voters)

    @property
    def votes_required(self) -> int:
        return self._votes_required

    @property
    def minimum_successful_votes(self) -> int:
        return self._minimum_successful_votes

    def classify(
        self,
        page: PageSnapshot,
    ) -> RepositoryClassification:
        outcomes = run_voters(
            self._voters,
            classify=lambda classifier: classifier.classify(page),
            make_vote=_repository_vote,
            handled_errors=(PageClassificationError, ValueError),
        )

        votes = [
            outcome.vote
            for outcome in outcomes
            if outcome.vote is not None
        ]

        failures = [
            {
                "voter_id": outcome.voter_id,
                "error": outcome.error,
                "errors": [item.to_dict() for item in outcome.diagnostics],
            }
            for outcome in outcomes
            if outcome.error
        ]

        if len(votes) < self._minimum_successful_votes:
            raise PageClassificationError(
                _minimum_votes_error(
                    self._minimum_successful_votes,
                    len(votes),
                    failures,
                ),
                diagnostics=[item for outcome in outcomes for item in outcome.diagnostics],
                code="classification_incomplete",
            )

        accepted_votes = sum(
            1
            for vote in votes
            if vote.accepted
        )

        accepted = accepted_votes >= self._votes_required

        # Only votes supporting the final accepted/rejected decision are used
        # when selecting the final relevance label.
        decision_votes = _repository_decision_votes(
            votes,
            accepted,
        )

        relevance_label = _majority_relevance_label(
            decision_votes
        )

        ensemble_summary = _ensemble_summary(
            voters=[_repository_vote_summary(vote) for vote in votes],
            failures=failures,
            votes_required=self._votes_required,
            minimum_successful_votes=self._minimum_successful_votes,
            accepted_votes=accepted_votes,
            decision="accepted" if accepted else "rejected",
            decision_reason=_repository_decision_reason(
                accepted=accepted,
                votes=votes,
                votes_required=self._votes_required,
            ),
            decision_voter_ids=[
                vote.voter_id
                for vote in decision_votes
            ],
        )

        return RepositoryClassification(
            relevance_label=relevance_label,
            reason=_relevance_reason(
                decision_votes,
                relevance_label,
            ),
            missing_information=_combined_missing_information(
                decision_votes,
                relevance_label,
            ),
            ensemble=ensemble_summary,
        )


def _repository_vote(
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


def _repository_decision_votes(
    votes: list[RepositoryClassificationVote],
    accepted: bool,
) -> list[RepositoryClassificationVote]:
    decision_votes = [
        vote
        for vote in votes
        if vote.accepted is accepted
    ]

    if not decision_votes:
        raise PageClassificationError(
            "No repository classifier vote supports the ensemble decision."
        )

    return decision_votes


def _repository_decision_reason(
    *,
    accepted: bool,
    votes: list[RepositoryClassificationVote],
    votes_required: int,
) -> str:
    if accepted:
        return "enough_accept_votes"

    rejected_votes = sum(
        1
        for vote in votes
        if not vote.accepted
    )

    if rejected_votes >= votes_required:
        return "rejected_by_majority"

    return "insufficient_accept_votes"


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

    raise PageClassificationError(
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
