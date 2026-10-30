"""Deadline-aware urllib transports, independent of public-network policy.

The raw reader is checked before every socket read. A peer cannot extend an
exchange by trickling status lines, headers, chunk framing or response bytes.
DNS waits use a bounded daemon resolver and share the connection deadline.
"""

from __future__ import annotations

import io
import socket
from http.client import HTTPConnection, HTTPResponse, HTTPSConnection
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler

from collector.budget import (
    RequestBudget,
    active_request_budget,
    check_request_budget,
    remaining_timeout,
    request_budget,
)
from collector.network.resolver import resolve_addresses


class _DeadlineReader(io.RawIOBase):
    def __init__(self, raw, sock, budget: RequestBudget):
        self._raw, self._sock, self._budget = raw, sock, budget
        self._timeout = sock.gettimeout() if hasattr(sock, "gettimeout") else None

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self._budget.remaining()
        timeout = remaining if self._timeout is None else min(self._timeout, remaining)
        self._sock.settimeout(timeout)
        try:
            count = self._raw.readinto(buffer)
        except OSError:
            self._budget.remaining()
            raise
        self._budget.remaining()
        return count

    def close(self):
        try:
            self._raw.close()
        finally:
            super().close()


class _ResponseSocket:
    def __init__(self, sock, budget):
        self.sock, self.budget = sock, budget

    def makefile(self, mode):
        raw = self.sock.makefile(mode, 0)
        try:
            return io.BufferedReader(_DeadlineReader(raw, self.sock, self.budget))
        except BaseException:
            raw.close()
            raise


class DeadlineHTTPResponse(HTTPResponse):
    def __init__(self, sock, *args, **kwargs):
        self._budget = active_request_budget()
        if self._budget is not None:
            sock = _ResponseSocket(sock, self._budget)
        super().__init__(sock, *args, **kwargs)

    def _bounded(self, operation, *args):
        try:
            if self._budget is not None:
                self._budget.remaining()
            result = operation(*args)
            if self._budget is not None:
                self._budget.remaining()
            return result
        except BaseException:
            self.close()
            raise

    def begin(self):
        return self._bounded(super().begin)

    def read(self, amt=None):
        return self._bounded(super().read, amt)

    def read1(self, n=-1):
        return self._bounded(super().read1, n)

    def readinto(self, buffer):
        return self._bounded(super().readinto, buffer)


def _connect_with_deadline(address, timeout, source_address=None):
    with request_budget(seconds=timeout):
        return _connect_resolved_with_deadline(address, timeout, source_address)


def _connect_resolved_with_deadline(address, timeout, source_address):
    host, port = address
    check_request_budget()
    addresses = resolve_addresses(host, port, 0, socket.SOCK_STREAM, timeout=timeout)
    check_request_budget()
    last_error = OSError("DNS returned no usable addresses.")
    for family, socktype, proto, _, sockaddr in addresses:
        check_request_budget()
        connection = None
        try:
            connection = socket.socket(family, socktype, proto)
            connection.settimeout(remaining_timeout(timeout))
            if source_address:
                connection.bind(source_address)
            connection.connect(sockaddr)
            check_request_budget()
            return connection
        except OSError as exception:
            last_error = exception
            if connection is not None:
                connection.close()
            check_request_budget()
        except BaseException:
            if connection is not None:
                connection.close()
            raise
    raise last_error


class _DeadlineConnectionMixin:
    response_class = DeadlineHTTPResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_with_deadline

    def send(self, data):
        try:
            check_request_budget()
            if self.sock is None:
                self.connect()
            self.sock.settimeout(remaining_timeout(self.timeout))
            super().send(data)
            check_request_budget()
        except BaseException:
            self.close()
            raise


class DeadlineHTTPConnection(_DeadlineConnectionMixin, HTTPConnection):
    pass


class DeadlineHTTPSConnection(_DeadlineConnectionMixin, HTTPSConnection):
    def connect(self):
        try:
            HTTPConnection.connect(self)
            self.sock.settimeout(remaining_timeout(self.timeout))
            self.sock = self._context.wrap_socket(
                self.sock, server_hostname=self._tunnel_host or self.host,
            )
            check_request_budget()
        except BaseException:
            self.close()
            raise


class DeadlineHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(DeadlineHTTPConnection, request)


class DeadlineHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        options = {"context": self._context}
        if hasattr(self, "_check_hostname"):  # Python 3.12 removed this parameter.
            options["check_hostname"] = self._check_hostname
        return self.do_open(DeadlineHTTPSConnection, request, **options)


class RejectHTTPRedirects(HTTPRedirectHandler):
    """Authenticated control endpoints must answer directly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
