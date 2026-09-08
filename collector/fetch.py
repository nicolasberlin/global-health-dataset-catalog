"""Bounded HTTP fetching with public-network URL enforcement."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from http.client import HTTPConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from collector.config import DEFAULT_CONFIG
from collector.network_policy import is_public_address


class PageFetchError(RuntimeError):
    """Raised when an HTML page could not be retrieved for classification."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    html: str
    status_code: int
    content_type: str


def fetch_public_html(
    url: str,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_bytes: int = 1_000_000,
) -> FetchedPage:
    """Fetch and decode a bounded response requested as HTML.

    The initial URL and every redirect are checked by
    ``open_public_http_url``. Reading one byte beyond ``max_bytes`` detects an
    oversized response; HTTP and transport failures are reported as
    ``PageFetchError`` so they cannot be mistaken for semantic rejection.
    """

    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": DEFAULT_CONFIG.user_agent,
        },
        method="GET",
    )

    try:
        with open_public_http_url(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise PageFetchError("HTML response is too large for collection.")
            return FetchedPage(
                url=url,
                final_url=response.geturl(),
                html=_decode_html(body, content_type),
                status_code=response.status,
                content_type=content_type,
            )
    except HTTPError as exception:
        raise PageFetchError(f"URL returned HTTP {exception.code}.") from exception
    except (TimeoutError, URLError, OSError) as exception:
        raise PageFetchError(f"Could not fetch URL: {exception}") from exception


def _ensure_public_http_url(url: str) -> None:
    """Validate URL syntax and literal IPs; DNS is checked at connection time."""

    if "\\" in url or any(ord(character) <= 32 or ord(character) == 127 for character in url):
        raise ValueError("URL contains invalid characters.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs can be analyzed.")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not supported.")
    if "%" in parsed.hostname:
        raise ValueError("Scoped or percent-encoded hostnames are not supported.")
    if parsed.port == 0:
        raise ValueError("URL port must be between 1 and 65535.")

    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return  # A hostname is resolved once, by _connect_public.
    if not is_public_address(address):
        raise ValueError("Private or local network URLs cannot be fetched.")


def _connect_public(host: str, port: int, timeout: float) -> socket.socket:
    """Connect only to numeric addresses from one fully validated DNS answer."""

    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    if not addresses:
        raise OSError("DNS returned no addresses.")
    for family, _, _, _, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6} or not is_public_address(
            ipaddress.ip_address(sockaddr[0])
        ):
            raise ValueError("Private or local network URLs cannot be fetched.")

    last_error = OSError("No public address could be reached.")
    for family, socktype, proto, _, sockaddr in addresses:
        connection = None
        try:
            connection = socket.socket(family, socktype, proto)
            connection.settimeout(timeout)
            # sockaddr contains a numeric IP, never the hostname. No second DNS lookup.
            connection.connect(sockaddr)
            return connection
        except OSError as exception:
            last_error = exception
            if connection is not None:
                connection.close()
    raise last_error


class _PublicHTTPConnection(HTTPConnection):
    def connect(self):
        if self._tunnel_host:
            raise ValueError("HTTP tunnels are not supported.")
        self.sock = _connect_public(self.host, self.port, self.timeout)


class _PublicHTTPSConnection(_PublicHTTPConnection):
    default_port = 443

    def connect(self):
        # Build the context before opening a socket so context failures cannot leak it.
        context = ssl.create_default_context()
        context.set_alpn_protocols(["http/1.1"])
        super().connect()
        try:
            self.sock = context.wrap_socket(self.sock, server_hostname=self.host)
        except Exception:
            self.close()
            raise


class _PublicHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(_PublicHTTPConnection, request)


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PublicHTTPSConnection, request)


class _PublicHTTPRedirectHandler(HTTPRedirectHandler):
    """Reapply public-network validation before following each redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ensure_public_http_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and req.get_method() == "HEAD":
            # urllib otherwise turns HEAD probes into GET requests on redirects.
            redirected.method = "HEAD"
        return redirected


def open_public_http_url(request: Request, *, timeout: float):
    """Open an untrusted URL after validating it and every redirect.

    URL validation and opener errors intentionally propagate so callers can
    either convert them to a rejected probe or abort their operation.
    """
    _ensure_public_http_url(request.full_url)
    if request.has_proxy() or request._tunnel_host:
        raise ValueError("Explicit proxies are not supported for public URL fetching.")
    return build_opener(
        ProxyHandler({}),
        _PublicHTTPHandler(),
        _PublicHTTPSHandler(),
        _PublicHTTPRedirectHandler(),
    ).open(request, timeout=timeout)


def _decode_html(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip()
            break

    return body.decode(charset, errors="replace")
