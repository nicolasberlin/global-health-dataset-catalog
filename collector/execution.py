"""Bounded thread execution with cooperative cancellation and no exit-time join.

Python cannot interrupt an in-flight synchronous call. Daemon workers allow a
bounded application shutdown; cancelled work cannot start another operation or
persist a late result through the thread bridges.
"""

from __future__ import annotations

from concurrent.futures import CancelledError, Executor, Future, TimeoutError
from contextvars import ContextVar
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread


class ExecutionStopped(BaseException):
    """Cancellation must not be mistaken for a retryable domain failure."""


@dataclass(eq=False)
class ExecutionControl:
    stopped: Event = field(default_factory=Event)
    _futures: set[Future] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)

    def abort(self) -> None:
        self.stopped.set()
        with self._lock:
            futures = tuple(self._futures)
        for future in futures:
            future.cancel()

    def register(self, future: Future) -> None:
        with self._lock:
            if self.stopped.is_set():
                future.cancel()
            else:
                self._futures.add(future)

    def unregister(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)


execution_control: ContextVar[ExecutionControl | None] = ContextVar(
    "execution_control", default=None
)


def check_execution_active() -> None:
    control = execution_control.get()
    if control is not None and control.stopped.is_set():
        raise ExecutionStopped()


def wait_for_future(future: Future):
    """Cancel a submitted bridge as soon as its worker loses ownership."""
    control = execution_control.get()
    if control is not None:
        control.register(future)
    try:
        while True:
            check_execution_active()
            try:
                return future.result(timeout=0.05)
            except CancelledError:
                check_execution_active()
                raise
            except TimeoutError:
                if future.done():
                    return future.result()  # Preserve an operation's own TimeoutError.
    finally:
        if control is not None:
            control.unregister(future)
            if control.stopped.is_set():
                future.cancel()


class BoundedThreadExecutor(Executor):
    """Small executor using public Future APIs, a bounded queue and daemon threads."""

    def __init__(self, max_workers: int, thread_name_prefix: str = "worker"):
        if max_workers < 1:
            raise ValueError("Worker concurrency must be positive.")
        self._queue = Queue(maxsize=max_workers)
        self._shutdown = Event()
        self._lock = Lock()
        self._threads = [
            Thread(target=self._run, name=f"{thread_name_prefix}-{index}", daemon=True)
            for index in range(max_workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, fn, /, *args, **kwargs):
        check_execution_active()
        future = Future()
        with self._lock:
            if self._shutdown.is_set():
                raise RuntimeError("Cannot submit work after executor shutdown.")
            try:
                self._queue.put_nowait((future, fn, args, kwargs, execution_control.get()))
            except Full as exception:
                raise RuntimeError("Worker executor queue is full.") from exception
        return future

    def _run(self):
        while True:
            try:
                future, fn, args, kwargs, control = self._queue.get(timeout=0.05)
            except Empty:
                if self._shutdown.is_set():
                    return
                continue
            try:
                if not future.set_running_or_notify_cancel():
                    continue
                if control is not None and control.stopped.is_set():
                    raise ExecutionStopped()
                future.set_result(fn(*args, **kwargs))
            except BaseException as exception:
                if not future.done():
                    future.set_exception(exception)
            finally:
                self._queue.task_done()

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self._lock:
            self._shutdown.set()
            if cancel_futures:
                while True:
                    try:
                        future, *_ = self._queue.get_nowait()
                    except Empty:
                        break
                    future.cancel()
                    self._queue.task_done()
        if wait:
            control = execution_control.get()
            for thread in self._threads:
                while thread.is_alive():
                    if control is not None and control.stopped.is_set():
                        return
                    thread.join(timeout=0.05)
