"""Aggregate dataset page eligibility votes."""

from __future__ import annotations

from collector.collection.eligibility.models import (
    PageClassification,
    PageClassificationVote,
    PageClassifier,
)
from collector.llm.errors import ClassificationError
from collector.llm.voting import VotingEnsemble
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
        self._voting = VotingEnsemble(
            voters,
            minimum_accept_votes=votes_required,
            minimum_successful_votes=minimum_successful_votes,
            name="EnsemblePageClassifier",
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
        distributions: list[DistributionCandidate],
    ) -> PageClassification:
        voting_result = self._voting.evaluate(
            classify=lambda classifier: classifier.classify(page, distributions),
            make_vote=_to_page_eligibility_vote,
            handled_errors=(ClassificationError,),
        )
        if not voting_result.supporting_votes:
            raise ClassificationError("No classifier vote supports the ensemble decision.")

        return PageClassification(
            accepted=voting_result.accepted,
            dataset_signals={"ensemble": voting_result.to_summary(_vote_summary)},
        )


def _to_page_eligibility_vote(
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
