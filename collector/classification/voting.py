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
