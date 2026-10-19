"""Worker ownership and health shared by persistence and shutdown."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass

from collector.execution import ExecutionControl


@dataclass(eq=False)
class ShutdownBudget:
    seconds: float
    deadline: float | None = None

    def start(self) -> None:
        if self.deadline is None:
            self.deadline = asyncio.get_running_loop().time() + self.seconds


shutdown_budget: ContextVar[ShutdownBudget | None] = ContextVar("shutdown_budget", default=None)


@dataclass(eq=False)
class WorkerState:
    queue: str
    stop: asyncio.Event
    control: ExecutionControl
    budget: ShutdownBudget
    blocked_persistence: int = 0
    acquisition_failed: bool = False
    failed: bool = False
    task: asyncio.Task | None = None

    @property
    def persistence_blocked(self) -> bool:
        return self.blocked_persistence > 0


current_worker: ContextVar[WorkerState | None] = ContextVar("current_worker", default=None)
_active_workers: set[WorkerState] = set()


def workers_ready() -> bool:
    return all(
        not worker.persistence_blocked and not worker.acquisition_failed and not worker.failed
        for worker in _active_workers
    )


def request_worker_stop(*, force: bool = False) -> None:
    """Stop admission to every queue; force also fences threads and cancels bridges."""
    for worker in tuple(_active_workers):
        worker.budget.start()
        worker.stop.set()
        if force:
            worker.control.abort()
            if worker.task is not None:
                worker.task.cancel()


def register_worker(worker: WorkerState) -> None:
    _active_workers.add(worker)


def unregister_worker(worker: WorkerState) -> None:
    _active_workers.discard(worker)
