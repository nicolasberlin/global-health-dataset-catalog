"""OS DNS resolution with bounded callers and a fixed number of daemon workers.

An OS lookup cannot be interrupted. Its slot stays occupied until it actually
finishes, even after the caller's deadline or cancellation.
"""

from __future__ import annotations

import socket
from concurrent.futures import TimeoutError
from threading import BoundedSemaphore, Lock

from collector.budget import check_request_budget, remaining_timeout, request_budget
from collector.execution import BoundedThreadExecutor, execution_control

_WORKERS = 4
_WAIT_SECONDS = 0.05


class _AddressResolver:
    def __init__(self):
        self._capacity = BoundedSemaphore(_WORKERS)
        self._executor = BoundedThreadExecutor(_WORKERS, thread_name_prefix="dns")

    def resolve(self, *args, **kwargs):
        while True:
            check_request_budget()
            if self._capacity.acquire(timeout=min(_WAIT_SECONDS, remaining_timeout(float("inf")))):
                break
        try:
            check_request_budget()
            future = self._executor.submit(socket.getaddrinfo, *args, **kwargs)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _future: self._capacity.release())
        control = execution_control.get()
        if control is not None:
            control.register(future)
        try:
            while True:
                check_request_budget()
                try:
                    result = future.result(
                        timeout=min(_WAIT_SECONDS, remaining_timeout(float("inf"))),
                    )
                except TimeoutError:
                    if not future.done():
                        continue
                    check_request_budget()
                    return future.result()  # Preserve the resolver's own timeout.
                except BaseException:
                    check_request_budget()
                    raise
                check_request_budget()
                return result
        finally:
            if control is not None:
                control.unregister(future)
            future.cancel()


_resolver: _AddressResolver | None = None
_resolver_lock = Lock()


def resolve_addresses(*args, timeout: float, **kwargs):
    """Preserve getaddrinfo arguments and charge admission and DNS to the request."""
    global _resolver
    with request_budget(seconds=timeout):
        check_request_budget()
        with _resolver_lock:
            if _resolver is None:
                _resolver = _AddressResolver()
            resolver = _resolver
        return resolver.resolve(*args, **kwargs)
