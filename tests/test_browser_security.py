from __future__ import annotations

import socket
import threading
from urllib.error import HTTPError

import pytest

from backend.container_entrypoint import build_rules
from browser.container_entrypoint import rules
from browser.public_proxy import BoundedProxyServer, PublicProxy
from collector.collection.browser import BrowserSession
from collector.config import DEFAULT_CONFIG
from collector.fetch import PageFetchError


@pytest.fixture
def proxy():
    server = BoundedProxyServer(("127.0.0.1", 0), PublicProxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "authority",
    [
        "127.0.0.1:443",
        "169.254.169.254:443",
        "10.0.0.1:443",
        "example.org:8001",
        "user@example.org:443",
        "[::1]:443",
    ],
)
def test_proxy_refuses_private_destinations_and_non_tls_ports(proxy, authority):
    with socket.create_connection(proxy, timeout=2) as connection:
        connection.sendall(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
        assert b"403" in connection.recv(1024).split(b"\r\n", 1)[0]


def test_browser_firewall_blocks_private_ranges_and_keeps_only_proxy_exception():
    policy = rules(["127.0.0.11"], "8.8.8.0/24")
    assert "ip daddr 127.0.0.1 tcp dport 8899 accept" in policy
    assert "tcp dport 5432 accept" not in policy
    assert policy.index("ip daddr 8.8.8.0/24 drop") < policy.index("tcp dport 443 accept")
    assert policy.index("ip daddr 127.0.0.0/8 drop") < policy.index("tcp dport 443 accept")
    api_policy = build_rules(["10.0.0.2"], ["127.0.0.11"], browser_addresses=["10.0.0.3"])
    assert "ip daddr 10.0.0.3 tcp dport 8002 accept" in api_policy
    assert "ip daddr 10.0.0.3 tcp dport 5432 accept" not in api_policy


def test_browser_capacity_wait_is_bounded_even_without_a_collection_context(monkeypatch):
    class Busy:
        def open(self, *args, **kwargs):
            raise HTTPError("http://renderer/render", 429, "Busy", {}, None)

    ticks = iter([0, 31])
    monkeypatch.setattr("collector.collection.browser.build_opener", lambda *args: Busy())
    monkeypatch.setattr("collector.collection.browser.time.monotonic", lambda: next(ticks))
    session = BrowserSession("http://renderer", "test", DEFAULT_CONFIG)
    with pytest.raises(PageFetchError) as caught:
        session.render("https://dataverse.harvard.edu/")
    assert caught.value.diagnostics[0].code == "browser_unavailable"
