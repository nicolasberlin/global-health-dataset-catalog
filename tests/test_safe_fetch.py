from __future__ import annotations

import io
import socket
import ssl
import subprocess
import threading
from email.message import Message
from urllib.error import URLError
from urllib.request import Request

import pytest

from collector.fetch import (
    PageFetchError,
    _connect_public,
    _PublicHTTPRedirectHandler,
    fetch_public_html,
    open_public_http_url,
)
from collector.validation.downloads import probe_url


def test_public_http_fetch_blocks_private_url_before_opening(monkeypatch):
    opened = False

    def fail_if_opened(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("A private URL must not be opened.")

    monkeypatch.setattr("collector.fetch.build_opener", fail_if_opened)

    with pytest.raises(ValueError, match="Private or local"):
        open_public_http_url(Request("http://127.0.0.1/private"), timeout=1)

    assert opened is False


def test_public_http_redirect_handler_blocks_private_destination():
    handler = _PublicHTTPRedirectHandler()

    with pytest.raises(ValueError, match="Private or local"):
        handler.redirect_request(
            Request("https://public.example/file.csv"),
            None,
            302,
            "Found",
            Message(),
            "http://127.0.0.1/private",
        )


def test_distribution_probe_reports_private_url_as_invalid(monkeypatch):
    monkeypatch.setattr(
        "collector.fetch.build_opener",
        lambda *args, **kwargs: pytest.fail("A private distribution must not be opened."),
    )

    result = probe_url(
        "http://127.0.0.1/private.csv",
        method="HEAD",
        timeout=1,
        max_bytes=0,
    )

    assert result.status_code is None
    assert "Private or local" in result.error


def _address(value, port=80):
    family = socket.AF_INET6 if ":" in value else socket.AF_INET
    sockaddr = (value, port, 0, 0) if family == socket.AF_INET6 else (value, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


class _Socket:
    def __init__(self, response=b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok", error=None):
        self.response = response
        self.error = error
        self.sent = b""
        self.closed = False
        self.destination = None
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, destination):
        self.destination = destination
        if self.error:
            raise self.error

    def sendall(self, data):
        self.sent += data

    def makefile(self, *args):
        return io.BytesIO(self.response)

    def close(self):
        self.closed = True


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:4700:4700::1111"])
def test_dns_rebinding_cannot_change_the_connected_address(monkeypatch, address):
    lookups = []

    def changing_dns(host, port, **kwargs):
        lookups.append((host, port))
        return [_address(address if len(lookups) == 1 else "127.0.0.1", port)]

    connection = _Socket()
    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", changing_dns)
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *args: connection)

    with open_public_http_url(Request("http://rebind.example:8080/data"), timeout=2) as response:
        assert response.read() == b"ok"
        assert response.geturl() == "http://rebind.example:8080/data"

    assert lookups == [("rebind.example", 8080)]
    assert connection.destination == _address(address, 8080)[4]
    assert connection.timeout == 2
    assert b"Host: rebind.example:8080\r\n" in connection.sent


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "192.0.0.8",
        "198.18.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
        "2001::1",
        "3fff::1",
    ],
)
def test_mixed_dns_answers_are_rejected_before_any_socket(monkeypatch, address):
    monkeypatch.setattr(
        "collector.fetch.socket.getaddrinfo",
        lambda *args, **kwargs: [_address("93.184.216.34"), _address(address)],
    )
    monkeypatch.setattr(
        "collector.fetch.socket.socket", lambda *args: pytest.fail("Must not create a socket")
    )
    with pytest.raises(ValueError, match="Private or local"):
        open_public_http_url(Request("http://mixed.example/data"), timeout=1)


def test_redirect_revalidates_dns_even_for_the_same_hostname(monkeypatch):
    answers = iter([[_address("93.184.216.34")], [_address("127.0.0.1")]])
    connection = _Socket(b"HTTP/1.1 302 Found\r\nLocation: /internal\r\nContent-Length: 0\r\n\r\n")
    created = []

    def create_socket(*args):
        created.append(connection)
        return connection

    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", lambda *a, **kw: next(answers))
    monkeypatch.setattr("collector.fetch.socket.socket", create_socket)
    with pytest.raises(ValueError, match="Private or local"):
        open_public_http_url(Request("http://rebind.example/start"), timeout=1)
    assert len(created) == 1


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_public_redirect_preserves_method_and_reports_final_url(monkeypatch, method):
    first = _Socket(
        b"HTTP/1.1 302 Found\r\nLocation: http://other.example/data\r\nContent-Length: 0\r\n\r\n"
    )
    second = _Socket()
    connections = iter([first, second])
    hosts = []

    def resolve(host, port, **kwargs):
        hosts.append(host)
        return [_address("93.184.216.34", port)]

    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", resolve)
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: next(connections))
    with open_public_http_url(
        Request("http://public.example/", method=method), timeout=1
    ) as response:
        assert response.geturl() == "http://other.example/data"
        assert response.status == 200
    assert hosts == ["public.example", "other.example"]
    assert second.sent.startswith(f"{method} /data HTTP/1.1\r\n".encode())
    assert b"Host: other.example\r\n" in second.sent


def test_connection_failure_only_falls_back_to_validated_addresses(monkeypatch):
    first = _Socket(error=OSError("unreachable"))
    second = _Socket()
    connections = iter([first, second])
    monkeypatch.setattr(
        "collector.fetch.socket.getaddrinfo",
        lambda *a, **kw: [_address("93.184.216.34"), _address("93.184.216.35")],
    )
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: next(connections))
    assert _connect_public("public.example", 80, 1) is second
    assert first.closed
    assert second.destination == ("93.184.216.35", 80)


def test_empty_dns_answer_fails_closed(monkeypatch):
    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", lambda *a, **kw: [])
    with pytest.raises(URLError, match="DNS returned no addresses"):
        open_public_http_url(Request("http://empty.example/"), timeout=1)


def test_environment_proxy_is_ignored(monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9999")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    hosts = []

    def resolve(host, port, **kwargs):
        hosts.append(host)
        return [_address("93.184.216.34", port)]

    monkeypatch.setattr("collector.fetch.socket.getaddrinfo", resolve)
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: _Socket())
    with open_public_http_url(Request("http://public.example/"), timeout=1) as response:
        assert response.status == 200
    assert hosts == ["public.example"]


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_explicit_proxy_is_rejected(scheme):
    request = Request(f"{scheme}://public.example/")
    request.set_proxy("proxy.example:8080", scheme)
    with pytest.raises(ValueError, match="Explicit proxies"):
        open_public_http_url(request, timeout=1)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@public.example/",
        "http://public.example:0/",
        "http://public.example:99999/",
        "http://[fe80::1%25eth0]/",
        "http://public.example\\@127.0.0.1/",
    ],
)
def test_invalid_urls_are_rejected_before_dns(monkeypatch, url):
    monkeypatch.setattr(
        "collector.fetch.socket.getaddrinfo", lambda *a, **kw: pytest.fail("Must not resolve")
    )
    with pytest.raises(ValueError):
        open_public_http_url(Request(url), timeout=1)


def test_html_byte_limit_is_preserved(monkeypatch):
    monkeypatch.setattr(
        "collector.fetch.socket.getaddrinfo", lambda *a, **kw: [_address("93.184.216.34")]
    )
    monkeypatch.setattr("collector.fetch.socket.socket", lambda *a: _Socket())
    with pytest.raises(PageFetchError, match="too large"):
        fetch_public_html("http://public.example/", max_bytes=1)


@pytest.fixture(scope="module")
def tls_certificate(tmp_path_factory):
    directory = tmp_path_factory.mktemp("tls")
    certificate, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=public.example",
            "-addext",
            "subjectAltName=DNS:public.example",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    return certificate, key


@pytest.mark.parametrize(
    "hostname,trusted",
    [
        ("public.example", True),
        ("wrong.example", True),
        ("public.example", False),
    ],
)
def test_real_tls_preserves_sni_and_verifies_certificate(
    monkeypatch, tls_certificate, hostname, trusted
):
    certificate, key = tls_certificate
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    names, requests = [], []
    server_context.set_servername_callback(lambda sock, name, ctx: names.append(name))
    client_socket, server_socket = socket.socketpair()
    client_socket.settimeout(3)
    server_socket.settimeout(3)

    def serve():
        try:
            with server_context.wrap_socket(server_socket, server_side=True) as connection:
                requests.append(connection.recv(8192))
                connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except ssl.SSLError:
            pass  # Expected when the client rejects the certificate.

    default_context = ssl.create_default_context
    contexts = []

    def create_context():
        context = default_context()
        if trusted:
            context.load_verify_locations(cafile=str(certificate))
        contexts.append(context)
        return context

    monkeypatch.setattr("collector.fetch.ssl.create_default_context", create_context)
    monkeypatch.setattr("collector.fetch._connect_public", lambda *a: client_socket)
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        if trusted and hostname == "public.example":
            with open_public_http_url(Request(f"https://{hostname}/data"), timeout=3) as response:
                assert response.read() == b"ok"
            assert b"Host: public.example\r\n" in requests[0]
        else:
            with pytest.raises(URLError) as caught:
                open_public_http_url(Request(f"https://{hostname}/data"), timeout=3)
            assert isinstance(caught.value.reason, ssl.SSLCertVerificationError)
    finally:
        client_socket.close()
        thread.join(timeout=4)
        server_socket.close()
    assert not thread.is_alive()
    assert names == [hostname]
    assert contexts[0].check_hostname
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
