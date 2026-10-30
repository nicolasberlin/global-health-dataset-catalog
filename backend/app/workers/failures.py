"""Shared failure handling for model classification and collection attempts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Generic

from app.policies.retries import TRANSIENT
from app.workers.contracts import JobT, Persistence
from app.workers.sql_retries import persist_with_retry
from collector.diagnostics import Diagnostic, Stage, exception_diagnostics
from collector.observability import emit_event

RetryCallback = Callable[[JobT, list[Diagnostic]], Awaitable[tuple[bool, list[Diagnostic]]]]
FailureCallback = Callable[[JobT, str, list[Diagnostic]], Awaitable[object]]


class FailureHandler(Generic[JobT]):
    """Configure stable dependencies once; each handle call owns its diagnostics.

    The worker supplies fenced SQL operations for its queue. A model failure may
    requeue the existing attempt, while a failure saving an already computed
    outcome can only become a terminal persistence failure.
    """

    def __init__(
        self,
        *,
        stage: Stage,
        retry: RetryCallback[JobT],
        fail: FailureCallback[JobT],
        persist: Persistence | None = None,
    ) -> None:
        self._stage = stage
        self._retry = retry
        self._fail = fail
        self._persist = persist if persist is not None else persist_with_retry

    async def handle(self, job: JobT, exception: Exception, *, saving: bool) -> None:
        """Persist an automatic continuation or a final error without rerunning work.

        Retry scheduling retains the original model diagnostics during repairable
        SQL failures. A refused retry may enrich those diagnostics (for example
        with an expired collection budget); keep them for the terminal write.
        Cancellation and ownership loss propagate through the persistence policy.
        """
        emit_event(f"{self._stage}_execution", outcome="failed")
        error = str(exception) or type(exception).__name__
        diagnostics = (
            [Diagnostic("persistence_failed", self._stage)]
            if saving
            else exception_diagnostics(exception, self._stage)
        )
        if not saving and any(
            item.code in TRANSIENT | {"llm_invalid_response"} for item in diagnostics
        ):
            scheduled, diagnostics = await self._persist(
                lambda: self._retry(job, diagnostics),
                retry_storage_failures=True,
            )
            if scheduled:
                return
        await self._persist(
            lambda: self._fail(job, error, diagnostics),
            retry_storage_failures=True,
            retry_unexpected=True,
        )
