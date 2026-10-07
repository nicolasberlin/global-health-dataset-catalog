"""Cooperative collection deadline, shared across the existing worker threads.

An in-flight DNS lookup or blocking call cannot be forcibly cancelled. Callers
retain their worker until it returns; subsequent operations cannot start late.
Persistence is deliberately outside this budget.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from urllib.error import HTTPError

from collector.diagnostics import Diagnostic, PipelineFailure


class CollectionBudgetExceeded(PipelineFailure):
    def __init__(self):
        super().__init__(
            "Collection time budget exhausted.",
            diagnostics=[
                Diagnostic("collection_budget_exhausted", "collection"),
            ],
        )


@dataclass(frozen=True)
class CollectionBudget:
    deadline: float

    def remaining(self) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise CollectionBudgetExceeded()
        return remaining


_current: ContextVar[CollectionBudget | None] = ContextVar("collection_budget", default=None)


def active_collection_budget() -> CollectionBudget | None:
    return _current.get()


@contextmanager
def collection_budget(*, seconds: float = 180, deadline_at: datetime | str | None = None):
    """Reuse an inherited budget, or convert a persisted UTC deadline once."""
    inherited = _current.get()
    if inherited is not None:
        yield inherited
        return
    if deadline_at is not None:
        date = datetime.fromisoformat(deadline_at) if isinstance(deadline_at, str) else deadline_at
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        seconds = (date - datetime.now(timezone.utc)).total_seconds()
    budget = CollectionBudget(monotonic() + seconds)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def check_collection_budget() -> None:
    budget = _current.get()
    if budget is not None:
        budget.remaining()


def remaining_timeout(timeout: float) -> float:
    budget = _current.get()
    return min(timeout, budget.remaining()) if budget is not None else timeout


def read_with_budget(response, max_bytes: int) -> bytes:
    """Keep caller's byte bound; recheck time between bounded socket reads.

    read1 avoids waiting to fill a whole chunk on a slow HTTP stream. Socket
    access is optional for injected transports; their blocking behavior belongs
    to them. The timeout never increases beyond the existing socket timeout.
    """
    if _current.get() is None:
        return response.read(max_bytes)
    if isinstance(response, HTTPError):
        response = response.fp
    chunks = []
    left = max_bytes
    read = getattr(response, "read1", response.read)
    while left > 0:
        check_collection_budget()
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            timeout = sock.gettimeout()
            sock.settimeout(remaining_timeout(timeout if timeout is not None else float("inf")))
        try:
            chunk = read(min(left, 65_536))
        except OSError:
            check_collection_budget()
            raise
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
        if getattr(response, "length", None) == 0 or (
            callable(getattr(response, "isclosed", None)) and response.isclosed()
        ):
            break  # Preserve a complete response even if its last read used the budget.
    return b"".join(chunks)
