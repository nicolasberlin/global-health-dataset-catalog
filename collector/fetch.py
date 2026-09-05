"""Bounded HTTP fetching with public-network URL enforcement."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collector.config import DEFAULT_CONFIG


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
    oversized response; HTTP and transport failures are converted to
    ``ValueError`` for the collection pipeline.
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
                raise ValueError("HTML response is too large for the collector test panel.")
            return FetchedPage(
                url=url,
                final_url=response.geturl(),
                html=_decode_html(body, content_type),
                status_code=response.status,
                content_type=content_type,
            )
    except HTTPError as exception:
        raise ValueError(f"URL returned HTTP {exception.code}.") from exception
    except (TimeoutError, URLError, OSError) as exception:
        raise ValueError(f"Could not fetch URL: {exception}") from exception


def _ensure_public_http_url(url: str) -> None:
    """Reject non-HTTP URLs and blocked local or special-purpose addresses."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs can be analyzed.")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname.")

    for address_info in socket.getaddrinfo(parsed.hostname, None):
        ip_address = ipaddress.ip_address(address_info[4][0])
        if (
            ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_multicast
            or ip_address.is_reserved
            or ip_address.is_unspecified
        ):
            raise ValueError("Private or local network URLs cannot be fetched.")


class _PublicHTTPRedirectHandler(HTTPRedirectHandler):
    """Reapply public-network validation before following each redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ensure_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_public_http_url(request: Request, *, timeout: float):
    """Open an untrusted URL after validating it and every redirect.

    URL validation and opener errors intentionally propagate so callers can
    either convert them to a rejected probe or abort their operation.
    """
    _ensure_public_http_url(request.full_url)
    return build_opener(_PublicHTTPRedirectHandler()).open(request, timeout=timeout)


def _decode_html(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip()
            break

    return body.decode(charset, errors="replace")
