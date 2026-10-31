"""Parallel vote execution without domain-specific decision rules."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from collector.diagnostics import Diagnostic, voter_diagnostics
from collector.execution import (
    BoundedThreadExecutor,
    check_execution_active,
    execution_control,
    wait_for_future,
)

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
    voters: list[dict[str, object]],
    failures: list[dict[str, object]],
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
        "successful_votes": len(voters),
        "failed_votes": len(failures),
        "accepted_votes": accepted_votes,
        "decision": decision,
        "decision_reason": decision_reason,
        "decision_voter_ids": decision_voter_ids,
        "voters": voters,
        "failures": failures,
    }
