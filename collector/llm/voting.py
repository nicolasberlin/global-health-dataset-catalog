"""Shared parallel voting, acceptance thresholds and ensemble audit summaries."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from collector.diagnostics import Diagnostic, voter_diagnostics
from collector.execution import (
    BoundedThreadExecutor,
    check_execution_active,
    execution_control,
    wait_for_future,
)
from collector.llm.errors import ClassificationError

ClassifierT = TypeVar("ClassifierT")
ClassificationT = TypeVar("ClassificationT")
VoteT = TypeVar("VoteT")


@dataclass(frozen=True)
class VoteOutcome(Generic[VoteT]):
    voter_id: str
    vote: VoteT | None = None
    error: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)


def run_voters(
    voters: Sequence[tuple[str, ClassifierT]],
    *,
    classify: Callable[[ClassifierT], ClassificationT],
    make_vote: Callable[[str, ClassificationT], VoteT],
    handled_errors: tuple[type[Exception], ...],
) -> list[VoteOutcome[VoteT]]:
    """Keep voter order and catch only expected errors from classification.

    Vote construction and unexpected exceptions still fail the whole call.
    Each ensemble owns its error policy and the meaning of a usable vote.
    """
    if not voters:
        return []

    def invoke(voter: tuple[str, ClassifierT]) -> VoteOutcome[VoteT]:
        check_execution_active()
        voter_id, classifier = voter
        try:
            classification = classify(classifier)
        except handled_errors as exception:
            return VoteOutcome(voter_id=voter_id, error=str(exception) or type(exception).__name__,
                               diagnostics=voter_diagnostics(exception, voter_id))

        return VoteOutcome(
            voter_id=voter_id,
            vote=make_vote(voter_id, classification),
        )

    executor = BoundedThreadExecutor(max_workers=len(voters), thread_name_prefix="voter")
    try:
        futures = [executor.submit(copy_context().run, invoke, voter) for voter in voters]
        return [wait_for_future(future) for future in futures]
    finally:
        control = execution_control.get()
        executor.shutdown(wait=control is None or not control.stopped.is_set(), cancel_futures=True)


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


def _minimum_votes_error(
    minimum_successful_votes: int,
    successful_votes: int,
    failures: list[dict[str, object]],
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


class _AcceptanceVote(Protocol):
    """Minimal vote contract; feature-specific fields remain opaque to voting."""

    @property
    def voter_id(self) -> str: ...

    @property
    def accepted(self) -> bool: ...


EnsembleVoteT = TypeVar("EnsembleVoteT", bound=_AcceptanceVote)


@dataclass(frozen=True)
class EnsembleVotingResult(Generic[EnsembleVoteT]):
    """Usable votes, failures and the threshold decision, in configured voter order."""

    votes: list[EnsembleVoteT]
    voter_failures: list[dict[str, object]]
    accepted_votes: int
    accepted: bool
    supporting_votes: list[EnsembleVoteT]
    decision_reason: str
    minimum_accept_votes: int
    minimum_successful_votes: int

    def to_summary(
        self,
        summarize_vote: Callable[[EnsembleVoteT], dict[str, object]],
    ) -> dict[str, object]:
        """Keep the existing persisted summary keys and feature-specific vote fields."""
        return {
            "votes_required": self.minimum_accept_votes,
            "minimum_successful_votes": self.minimum_successful_votes,
            "successful_votes": len(self.votes),
            "failed_votes": len(self.voter_failures),
            "accepted_votes": self.accepted_votes,
            "decision": "accepted" if self.accepted else "rejected",
            "decision_reason": self.decision_reason,
            "decision_voter_ids": [vote.voter_id for vote in self.supporting_votes],
            "voters": [summarize_vote(vote) for vote in self.votes],
            "failures": self.voter_failures,
        }


class VotingEnsemble(Generic[ClassifierT]):
    """Execute voters and apply shared acceptance thresholds without interpreting labels."""

    def __init__(
        self,
        voters: Sequence[tuple[str, ClassifierT]],
        minimum_accept_votes: int = 2,
        minimum_successful_votes: int | None = None,
        *,
        name: str = "VotingEnsemble",
    ) -> None:
        # Wrappers supply their public class name to retain existing validation messages.
        if not voters:
            raise ValueError(f"{name} requires at least one voter.")
        voter_ids = [voter_id for voter_id, _classifier in voters]
        if len(set(voter_ids)) != len(voter_ids):
            raise ValueError(f"{name} voter ids must be unique.")

        self._voters = tuple(voters)
        self.minimum_accept_votes = minimum_accept_votes
        self.minimum_successful_votes = _validate_voting_thresholds(
            voter_count=len(self._voters),
            votes_required=minimum_accept_votes,
            minimum_successful_votes=minimum_successful_votes,
        )

    @property
    def voter_ids(self) -> tuple[str, ...]:
        return tuple(voter_id for voter_id, _classifier in self._voters)

    def evaluate(
        self,
        *,
        classify: Callable[[ClassifierT], ClassificationT],
        make_vote: Callable[[str, ClassificationT], EnsembleVoteT],
        handled_errors: tuple[type[Exception], ...],
    ) -> EnsembleVotingResult[EnsembleVoteT]:
        """Collect usable votes; preserve each feature's exception and conversion policy."""
        outcomes = run_voters(
            self._voters,
            classify=classify,
            make_vote=make_vote,
            handled_errors=handled_errors,
        )
        votes = [outcome.vote for outcome in outcomes if outcome.vote is not None]
        voter_failures = [
            {
                "voter_id": outcome.voter_id,
                "error": outcome.error,
                "errors": [item.to_dict() for item in outcome.diagnostics],
            }
            for outcome in outcomes
            if outcome.error
        ]
        if len(votes) < self.minimum_successful_votes:
            raise ClassificationError(
                _minimum_votes_error(
                    self.minimum_successful_votes, len(votes), voter_failures,
                ),
                diagnostics=[item for outcome in outcomes for item in outcome.diagnostics],
                code="classification_incomplete",
            )

        accepted_votes = sum(1 for vote in votes if vote.accepted)
        accepted = accepted_votes >= self.minimum_accept_votes
        supporting_votes = [vote for vote in votes if vote.accepted is accepted]
        if accepted:
            decision_reason = "enough_accept_votes"
        elif sum(1 for vote in votes if not vote.accepted) >= self.minimum_accept_votes:
            decision_reason = "rejected_by_majority"
        else:
            decision_reason = "insufficient_accept_votes"

        return EnsembleVotingResult(
            votes=votes,
            voter_failures=voter_failures,
            accepted_votes=accepted_votes,
            accepted=accepted,
            supporting_votes=supporting_votes,
            decision_reason=decision_reason,
            minimum_accept_votes=self.minimum_accept_votes,
            minimum_successful_votes=self.minimum_successful_votes,
        )
