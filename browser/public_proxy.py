"""HTTPS CONNECT proxy with DNS-pinned public-IP connections and bounded tunnels."""

from __future__ import annotations

import os
import select
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore
from time import monotonic

from collector.fetch import _connect_public


class BoundedProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class PublicProxy(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, *_):
        pass  # Do not log URLs or credentials.

    def do_CONNECT(self):  # noqa: N802
        upstream = None
        try:
            # HTTP CONNECT authority, never a URL, userinfo or arbitrary port.
            authority = self.path
            if authority.count(":") != 1:
                raise ValueError("Only DNS/IPv4 TLS authorities are supported")
            host, port = authority.rsplit(":", 1)
            if port != "443" or not host or any(c in host for c in "/@\\ \r\n"):
                raise ValueError("Invalid authority")
            upstream = _connect_public(host, 443, 5)
        except (OSError, ValueError):
            self.send_error(403, "Destination refused")
            return
        try:
            self.send_response(200, "Connection established")
            self.end_headers()
            sockets = [self.connection, upstream]
            deadline = monotonic() + 300
            remaining = 16 * 1024 * 1024
            while remaining > 0 and monotonic() < deadline:
                ready, _, _ = select.select(sockets, [], [], min(10, deadline - monotonic()))
                if not ready:
                    break
                for source in ready:
                    chunk = source.recv(min(65536, remaining))
                    if not chunk:
                        return
                    remaining -= len(chunk)
                    target = upstream if source is self.connection else self.connection
                    target.sendall(chunk)
        except (OSError, ValueError):
            pass
        finally:
            upstream.close()
            self.close_connection = True

    def do_GET(self):  # noqa: N802
        self.send_error(405, "Only TLS tunnels are allowed")


if __name__ == "__main__":
    BoundedProxyServer(
        (
            os.getenv("BROWSER_PROXY_BIND", "127.0.0.1"),
            int(os.getenv("BROWSER_PROXY_PORT", "8899")),
        ),
        PublicProxy,
    ).serve_forever()
