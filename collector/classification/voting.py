"""Parallel vote execution without domain-specific decision rules."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar

ClassifierT = TypeVar("ClassifierT")
ClassificationT = TypeVar("ClassificationT")
VoteT = TypeVar("VoteT")


@dataclass(frozen=True)
class VoteOutcome(Generic[VoteT]):
    voter_id: str
    vote: VoteT | None = None
    error: str = ""


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
        voter_id, classifier = voter
        try:
            classification = classify(classifier)
        except handled_errors as exception:
            return VoteOutcome(voter_id=voter_id, error=str(exception))

        return VoteOutcome(
            voter_id=voter_id,
            vote=make_vote(voter_id, classification),
        )

    with ThreadPoolExecutor(max_workers=len(voters)) as executor:
        return list(executor.map(invoke, voters))
