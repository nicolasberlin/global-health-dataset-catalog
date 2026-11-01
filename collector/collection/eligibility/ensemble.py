"""Aggregate dataset page eligibility votes."""

from __future__ import annotations

from collector.classification.errors import PageClassificationError
from collector.classification.voting import (
    _ensemble_summary,
    _minimum_votes_error,
    _validate_voting_thresholds,
    run_voters,
)
from collector.collection.eligibility.models import (
    PageClassification,
    PageClassificationVote,
    PageClassifier,
)
from collector.storage.models import DistributionCandidate, PageSnapshot


class EnsemblePageClassifier:
    """Run page classifiers in parallel and combine their votes by threshold.

    Classification fails when fewer than ``minimum_successful_votes`` voters
    return usable decisions.
    """

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
        outcomes = run_voters(
            self._voters,
            classify=lambda classifier: classifier.classify(page, distributions),
            make_vote=_page_vote,
            handled_errors=(PageClassificationError,),
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

        accepted_votes = sum(1 for vote in votes if vote.accepted)

        accepted = accepted_votes >= self._votes_required
        decision_votes = _decision_votes(votes, accepted)

        ensemble_arguments = dict(
            voters=[_vote_summary(vote) for vote in votes],
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
                )
            },
        )


def _page_vote(
    voter_id: str,
    classification: PageClassification,
) -> PageClassificationVote:
    return PageClassificationVote(
        voter_id=voter_id,
        accepted=classification.accepted,
        dataset_signals=classification.dataset_signals,
    )


def _vote_summary(
    vote: PageClassificationVote,
) -> dict[str, object]:
    return {
        "voter_id": vote.voter_id,
        "accepted": vote.accepted,
        "signals": vote.dataset_signals,
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
