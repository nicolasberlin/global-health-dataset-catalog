"""Cooperative collection deadline, shared across the existing worker threads.

DNS callers stop at their deadline while a bounded daemon resolver finishes any
in-flight OS lookup. Other injected blocking calls cannot be forcibly cancelled.
Subsequent operations cannot start late. Persistence is outside this budget.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from urllib.error import HTTPError

from collector.diagnostics import Diagnostic, PipelineFailure
from collector.execution import check_execution_active, execution_control


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
        check_execution_active()
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise CollectionBudgetExceeded()
        return remaining


_current: ContextVar[CollectionBudget | None] = ContextVar("collection_budget", default=None)


def active_collection_budget() -> CollectionBudget | None:
    return _current.get()


@contextmanager
def collection_budget(*, seconds: float = 300, deadline_at: datetime | str | None = None):
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
    check_execution_active()
    budget = _current.get()
    if budget is not None:
        budget.remaining()


@dataclass(frozen=True)
class RequestBudget:
    """One absolute deadline, retained by the response after opening it."""

    deadline: float

    def remaining(self) -> float:
        check_collection_budget()
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP request time budget exhausted.")
        return remaining


_request: ContextVar[RequestBudget | None] = ContextVar("request_budget", default=None)


def active_request_budget() -> RequestBudget | None:
    return _request.get()


@contextmanager
def request_budget(*, seconds: float):
    """Bound an exchange and its redirects without extending an inherited deadline.

    DNS admission, resolution and connection attempts consume the same deadline;
    an expired lookup cannot start a connection.
    """
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("HTTP request timeout must be positive and finite.")
    check_collection_budget()
    deadline = monotonic() + seconds
    for inherited in (_request.get(), _current.get()):
        if inherited is not None:
            deadline = min(deadline, inherited.deadline)
    budget = RequestBudget(deadline)
    token = _request.set(budget)
    try:
        yield budget
    finally:
        _request.reset(token)


@contextmanager
def cleanup_request_budget(*, seconds: float):
    """Allow one bounded cleanup exchange after its owner's deadline/cancellation."""
    collection_token = _current.set(None)
    request_token = _request.set(None)
    execution_token = execution_control.set(None)
    try:
        with request_budget(seconds=seconds) as budget:
            yield budget
    finally:
        execution_control.reset(execution_token)
        _request.reset(request_token)
        _current.reset(collection_token)


def check_request_budget() -> None:
    check_collection_budget()
    budget = _request.get()
    if budget is not None:
        budget.remaining()


def remaining_timeout(timeout: float) -> float:
    check_execution_active()
    budget = _current.get()
    if budget is not None:
        timeout = min(timeout, budget.remaining())
    request = _request.get()
    return min(timeout, request.remaining()) if request is not None else timeout


def read_with_budget(response, max_bytes: int) -> bytes:
    """Keep caller's byte bound; recheck time between bounded socket reads.

    read1 avoids waiting to fill a whole chunk on a slow HTTP stream. Socket
    access is optional for injected transports; their blocking behavior belongs
    to them. The timeout never increases beyond the existing socket timeout.
    """
    check_execution_active()
    if _current.get() is None and _request.get() is None:
        return response.read(max_bytes)
    if isinstance(response, HTTPError):
        response = response.fp
    chunks = []
    left = max_bytes
    read = getattr(response, "read1", response.read)
    while left > 0:
        check_request_budget()
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            timeout = sock.gettimeout()
            sock.settimeout(remaining_timeout(timeout if timeout is not None else float("inf")))
        try:
            chunk = read(min(left, 65_536))
        except OSError:
            check_request_budget()
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
