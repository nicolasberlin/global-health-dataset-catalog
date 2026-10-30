"""Structural contracts shared by durable workers and persistence callbacks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Executor
from typing import Protocol, TypeVar
from uuid import UUID

JobT = TypeVar("JobT", bound=Mapping[str, object])
ResultT = TypeVar("ResultT")


class Worker(Protocol[JobT]):
    """Describe one queue; per-attempt state belongs to execute's local variables."""

    @property
    def name(self) -> str: ...

    async def claim(self, *, claim_token: UUID) -> JobT | None:
        """Acquire or recover the same attempt when called again with this token."""
        ...

    async def execute(self, job: JobT, executor: Executor) -> None:
        """Process one claimed attempt and retain its outcome until persisted."""
        ...

    async def recover(self, job: JobT) -> object:
        """Record a guarded terminal failure after an unexpected execution error."""
        ...


class Persistence(Protocol):
    """Retry a SQL callback without repeating the work that produced its input."""

    async def __call__(
        self,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        retry_storage_failures: bool = False,
        retry_unexpected: bool = False,
    ) -> ResultT: ...
