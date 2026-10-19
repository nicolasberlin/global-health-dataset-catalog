"""A stalled OS resolver cannot hold HTTP callers or exhaust unbounded threads."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from collector import resolver
from collector.budget import CollectionBudgetExceeded, collection_budget
from collector.execution import ExecutionControl, ExecutionStopped, execution_control
from collector.fetch import _connect_public
from collector.transport import _connect_with_deadline


def address(ip="93.184.216.34", port=443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    destination = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", destination


@pytest.fixture
def pool(monkeypatch):
    instance = resolver._AddressResolver()
    monkeypatch.setattr(resolver, "_resolver", instance)
    yield instance
    instance._executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize("connect", [_connect_public, _connect_with_deadline])
@pytest.mark.parametrize("collection_seconds", [None, 0.05])
def test_blocked_lookup_returns_at_deadline_and_late_result_never_connects(
    monkeypatch, pool, connect, collection_seconds,
):
    started, release = threading.Event(), threading.Event()
    create_socket = Mock(side_effect=AssertionError("A late lookup cannot create a socket"))

    def lookup(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return [address()]

    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(resolver.socket, "socket", create_socket)

    def run():
        if connect is _connect_public:
            connect("public.example", 443, 0.15)
        else:
            connect(("internal.example", 443), 0.15)

    before = time.monotonic()
    try:
        if collection_seconds is None:
            with pytest.raises(socket.timeout):
                run()
        else:
            with collection_budget(seconds=collection_seconds):
                with pytest.raises(CollectionBudgetExceeded):
                    run()
        assert started.is_set()
        assert time.monotonic() - before < 0.8
        create_socket.assert_not_called()
    finally:
        release.set()
    pool._executor.shutdown(wait=True)
    create_socket.assert_not_called()


def test_timed_out_lookups_keep_four_slots_until_os_calls_finish(monkeypatch, pool):
    release = threading.Event()
    condition = threading.Condition()
    counts = {"started": 0, "running": 0, "maximum": 0, "finished": 0}
    failures = []

    def lookup(*args, **kwargs):
        with condition:
            counts["started"] += 1
            counts["running"] += 1
            counts["maximum"] = max(counts["maximum"], counts["running"])
            condition.notify_all()
        try:
            assert release.wait(3)
            return [address()]
        finally:
            with condition:
                counts["running"] -= 1
                counts["finished"] += 1
                condition.notify_all()

    def request():
        try:
            resolver.resolve_addresses("public.example", 443, timeout=0.2)
        except BaseException as exception:
            failures.append(exception)

    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    callers = [threading.Thread(target=request) for _ in range(4)]
    try:
        for caller in callers:
            caller.start()
        with condition:
            assert condition.wait_for(lambda: counts["started"] == 4, timeout=1)
        for caller in callers:
            caller.join(timeout=1)
            assert not caller.is_alive()
        assert len(failures) == 4 and all(isinstance(error, socket.timeout) for error in failures)
        for _ in range(3):
            with pytest.raises(socket.timeout):
                resolver.resolve_addresses("another.example", 443, timeout=0.05)
        assert counts["started"] == counts["maximum"] == 4
        release.set()
        with condition:
            assert condition.wait_for(lambda: counts["finished"] == 4, timeout=1)
        assert resolver.resolve_addresses("recovered.example", 443, timeout=1) == [address()]
        assert counts["maximum"] == 4
    finally:
        release.set()
        for caller in callers:
            caller.join(timeout=2)


def test_cancellation_during_lookup_returns_without_waiting_for_os(monkeypatch, pool):
    started, release = threading.Event(), threading.Event()
    control = ExecutionControl()

    def lookup(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return [address()]

    def cancel():
        assert started.wait(1)
        control.abort()

    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    create_socket = Mock(side_effect=AssertionError("Cancelled lookup cannot connect"))
    monkeypatch.setattr(resolver.socket, "socket", create_socket)
    token = execution_control.set(control)
    cancel_thread = threading.Thread(target=cancel)
    before = time.monotonic()
    try:
        cancel_thread.start()
        with pytest.raises(ExecutionStopped):
            _connect_public("public.example", 443, 2)
        assert time.monotonic() - before < 0.8
        create_socket.assert_not_called()
    finally:
        execution_control.reset(token)
        release.set()
        cancel_thread.join(timeout=1)


def test_cancellation_while_waiting_for_resolver_capacity(monkeypatch, pool):
    for _ in range(4):
        assert pool._capacity.acquire(blocking=False)
    lookup = Mock(side_effect=AssertionError("No resolver capacity available"))
    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    control = ExecutionControl()
    token = execution_control.set(control)
    timer = threading.Timer(0.05, control.abort)
    before = time.monotonic()
    try:
        timer.start()
        with pytest.raises(ExecutionStopped):
            resolver.resolve_addresses("public.example", 443, timeout=2)
        assert time.monotonic() - before < 0.8
        lookup.assert_not_called()
    finally:
        execution_control.reset(token)
        timer.cancel()
        timer.join(timeout=1)
        for _ in range(4):
            pool._capacity.release()


def test_dns_errors_propagate_and_release_capacity(monkeypatch, pool):
    failure = socket.gaierror(socket.EAI_NONAME, "synthetic missing host")
    monkeypatch.setattr(resolver.socket, "getaddrinfo", Mock(side_effect=failure))
    for _ in range(6):
        with pytest.raises(socket.gaierror) as caught:
            resolver.resolve_addresses("missing.example", 443, timeout=1)
        assert caught.value is failure


def test_collection_expiry_takes_priority_over_late_dns_error(monkeypatch, pool):
    now = [0.0]
    monkeypatch.setattr("collector.budget.monotonic", lambda: now[0])

    def lookup(*args, **kwargs):
        now[0] += 2
        raise socket.gaierror(socket.EAI_AGAIN, "synthetic DNS failure")

    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    with collection_budget(seconds=1), pytest.raises(CollectionBudgetExceeded):
        resolver.resolve_addresses("public.example", 443, timeout=5)


def test_resolver_preserves_all_getaddrinfo_arguments(monkeypatch, pool):
    lookup = Mock(return_value=[address("2606:4700:4700::1111")])
    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    result = resolver.resolve_addresses(
        "public.example", 443, socket.AF_UNSPEC, socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP, flags=socket.AI_ADDRCONFIG, timeout=1,
    )
    assert result == [address("2606:4700:4700::1111")]
    lookup.assert_called_once_with(
        "public.example", 443, socket.AF_UNSPEC, socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP, flags=socket.AI_ADDRCONFIG,
    )


@pytest.mark.parametrize("ip", ["127.0.0.1", "::1"])
def test_trusted_transport_preserves_internal_resolution_and_numeric_connection(
    monkeypatch, pool, ip,
):
    connection = Mock()
    lookup = Mock(return_value=[address(ip, 8080)])
    monkeypatch.setattr(resolver.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(resolver.socket, "socket", Mock(return_value=connection))
    assert _connect_with_deadline(("renderer", 8080), 1, ("0.0.0.0", 0)) is connection
    lookup.assert_called_once_with("renderer", 8080, 0, socket.SOCK_STREAM)
    connection.bind.assert_called_once_with(("0.0.0.0", 0))
    connection.connect.assert_called_once_with(address(ip, 8080)[4])


def test_process_exits_with_an_os_lookup_still_blocked():
    script = """
import socket
from threading import Event
from collector.resolver import resolve_addresses
socket.getaddrinfo = lambda *args, **kwargs: Event().wait()
try:
    resolve_addresses('blocked.example', 443, timeout=0.05)
except socket.timeout:
    pass
else:
    raise AssertionError('DNS did not stop at its deadline')
"""
    result = subprocess.run([sys.executable, "-c", script], timeout=3, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
