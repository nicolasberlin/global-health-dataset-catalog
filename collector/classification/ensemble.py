from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from collector.classification.page import (
    PageClassification,
    PageClassificationError,
    PageClassificationVote,
    PageClassifier,
)
from collector.classification.repository import (
    RepositoryClassification,
    RepositoryClassificationVote,
    RepositoryRelevanceLabel,
    RepositoryResultClassifier,
)
from collector.storage.models import DistributionCandidate, PageSnapshot

# Ties are resolved by selecting the first matching, most conservative label.
REPOSITORY_RELEVANCE_CONSERVATIVE_ORDER: tuple[RepositoryRelevanceLabel, ...] = (
    "not_relevant",
    "insufficient_information",
    "somewhat_relevant",
    "relevant",
)


def _validate_voting_thresholds(
    *,
    voter_count: int,
    votes_required: int,
    minimum_successful_votes: int | None,
) -> int:
    minimum = (
        votes_required
        if minimum_successful_votes is None
        else minimum_successful_votes
    )

    if votes_required < 1:
        raise ValueError("votes_required must be at least 1.")
    if minimum < 1:
        raise ValueError("minimum_successful_votes must be at least 1.")
    if votes_required > voter_count:
        raise ValueError("votes_required cannot exceed voter count.")
    if minimum > voter_count:
        raise ValueError("minimum_successful_votes cannot exceed voter count.")
    if minimum < votes_required:
        raise ValueError(
            "minimum_successful_votes cannot be lower than votes_required."
        )

    return minimum


class EnsemblePageClassifier:
    """Combine independent page-classifier votes into one decision."""

    def __init__(
        self,
        voters: list[tuple[str, PageClassifier]] | tuple[tuple[str, PageClassifier], ...],
        votes_required: int = 2,
        minimum_successful_votes: int | None = None,
    ) -> None:
        if not voters:
            raise ValueError("EnsemblePageClassifier requires at least one voter.")

        voter_ids = [voter_id for voter_id, _classifier in voters]

        if len(set(voter_ids)) != len(voter_ids):
            raise ValueError("EnsemblePageClassifier voter ids must be unique.")

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
        distributions: list[DistributionCandidate],
    ) -> PageClassification:
        outcomes = self._classify_voters(page, distributions)
        votes = [
            outcome.vote
            for outcome in outcomes
            if outcome.vote is not None
        ]

        failures = [
            {
                "voter_id": outcome.voter_id,
                "error": outcome.error,
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
                )
            )

        accepted_votes = sum(1 for vote in votes if vote.accepted)

        accepted = accepted_votes >= self._votes_required
        decision_votes = _decision_votes(votes, accepted)

        ensemble_arguments = dict(
            votes=votes,
            failures=failures,
            votes_required=self._votes_required,
            minimum_successful_votes=self._minimum_successful_votes,
            accepted_votes=accepted_votes,
            decision="accepted" if accepted else "rejected",
            decision_reason=_decision_reason(
                accepted=accepted,
                votes=votes,
                votes_required=self._votes_required,
            ),
            decision_voter_ids=[
                vote.voter_id
                for vote in decision_votes
            ],
        )

        return PageClassification(
            accepted=accepted,
            dataset_signals={
                "ensemble": _ensemble_summary(
                    **ensemble_arguments,
                    signal_kind="dataset",
                )
            },
            health_signals={
                "ensemble": _ensemble_summary(
                    **ensemble_arguments,
                    signal_kind="health",
                )
            },
        )

    def _classify_voters(
        self,
        page: PageSnapshot,
        distributions: list[DistributionCandidate],
    ) -> list[_VoteOutcome]:
        with ThreadPoolExecutor(max_workers=len(self._voters)) as executor:
            return list(
                executor.map(
                    lambda voter: _classify_voter(
                        voter,
                        page,
                        distributions,
                    ),
                    self._voters,
                )
            )


class EnsembleRepositoryRelevanceClassifier:
    """Combine independent repository-relevance votes into one decision."""

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
        outcomes = self._classify_voters(page)

        votes = [
            outcome.vote
            for outcome in outcomes
            if outcome.vote is not None
        ]

        failures = [
            {
                "voter_id": outcome.voter_id,
                "error": outcome.error,
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
                )
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

        ensemble_summary = _repository_ensemble_summary(
            votes=votes,
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

    def _classify_voters(
        self,
        page: PageSnapshot,
    ) -> list[_RepositoryVoteOutcome]:
        with ThreadPoolExecutor(max_workers=len(self._voters)) as executor:
            return list(
                executor.map(
                    lambda voter: _classify_repository_voter(
                        voter,
                        page,
                    ),
                    self._voters,
                )
            )


@dataclass(frozen=True)
class _VoteOutcome:
    voter_id: str
    vote: PageClassificationVote | None = None
    error: str = ""


@dataclass(frozen=True)
class _RepositoryVoteOutcome:
    voter_id: str
    vote: RepositoryClassificationVote | None = None
    error: str = ""


def _classify_voter(
    voter: tuple[str, PageClassifier],
    page: PageSnapshot,
    distributions: list[DistributionCandidate],
) -> _VoteOutcome:
    voter_id, classifier = voter

    try:
        classification = classifier.classify(
            page,
            distributions,
        )
    except PageClassificationError as exception:
        return _VoteOutcome(
            voter_id=voter_id,
            error=str(exception),
        )

    return _VoteOutcome(
        voter_id=voter_id,
        vote=PageClassificationVote(
            voter_id=voter_id,
            accepted=classification.accepted,
            dataset_signals=classification.dataset_signals,
            health_signals=classification.health_signals,
        ),
    )


def _classify_repository_voter(
    voter: tuple[str, RepositoryResultClassifier],
    page: PageSnapshot,
) -> _RepositoryVoteOutcome:
    voter_id, classifier = voter

    try:
        classification = classifier.classify(page)
    except (PageClassificationError, ValueError) as exception:
        return _RepositoryVoteOutcome(
            voter_id=voter_id,
            error=str(exception),
        )

    return _RepositoryVoteOutcome(
        voter_id=voter_id,
        vote=RepositoryClassificationVote(
            voter_id=voter_id,
            relevance_label=classification.relevance_label,
            reason=classification.reason,
            missing_information=list(
                classification.missing_information
            ),
        ),
    )


def _minimum_votes_error(
    minimum_successful_votes: int,
    successful_votes: int,
    failures: list[dict[str, str]],
) -> str:
    failure_summary = "; ".join(
        f"{failure['voter_id']}: {failure['error']}"
        for failure in failures
    )

    message = (
        f"At least {minimum_successful_votes} classifier votes are required; "
        f"{successful_votes} succeeded."
    )

    if failure_summary:
        return f"{message} Failures: {failure_summary}"

    return message


def _ensemble_summary(
    *,
    votes: list[PageClassificationVote],
    failures: list[dict[str, str]],
    votes_required: int,
    minimum_successful_votes: int,
    accepted_votes: int,
    decision: str,
    decision_reason: str,
    decision_voter_ids: list[str],
    signal_kind: str,
) -> dict[str, object]:
    return {
        "votes_required": votes_required,
        "minimum_successful_votes": minimum_successful_votes,
        "successful_votes": len(votes),
        "failed_votes": len(failures),
        "accepted_votes": accepted_votes,
        "decision": decision,
        "decision_reason": decision_reason,
        "decision_voter_ids": decision_voter_ids,
        "voters": [
            _vote_summary(vote, signal_kind)
            for vote in votes
        ],
        "failures": failures,
    }


def _vote_summary(
    vote: PageClassificationVote,
    signal_kind: str,
) -> dict[str, object]:
    signals = (
        vote.dataset_signals
        if signal_kind == "dataset"
        else vote.health_signals
    )

    return {
        "voter_id": vote.voter_id,
        "accepted": vote.accepted,
        "signals": signals,
    }


def _repository_ensemble_summary(
    *,
    votes: list[RepositoryClassificationVote],
    failures: list[dict[str, str]],
    votes_required: int,
    minimum_successful_votes: int,
    accepted_votes: int,
    decision: str,
    decision_reason: str,
    decision_voter_ids: list[str],
) -> dict[str, object]:
    return {
        "votes_required": votes_required,
        "minimum_successful_votes": minimum_successful_votes,
        "successful_votes": len(votes),
        "failed_votes": len(failures),
        "accepted_votes": accepted_votes,
        "decision": decision,
        "decision_reason": decision_reason,
        "decision_voter_ids": decision_voter_ids,
        "voters": [
            _repository_vote_summary(vote)
            for vote in votes
        ],
        "failures": failures,
    }


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


def _decision_votes(
    votes: list[PageClassificationVote],
    accepted: bool,
) -> list[PageClassificationVote]:
    decision_votes = [
        vote
        for vote in votes
        if vote.accepted is accepted
    ]

    if not decision_votes:
        raise PageClassificationError(
            "No classifier vote supports the ensemble decision."
        )

    return decision_votes


def _decision_reason(
    *,
    accepted: bool,
    votes: list[PageClassificationVote],
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
