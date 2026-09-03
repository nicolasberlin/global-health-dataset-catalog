from __future__ import annotations

import re
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from collector.config import DEFAULT_CONFIG
from collector.extraction.distributions import guess_format
from collector.fetch import open_public_http_url
from collector.storage.models import DistributionCandidate, HTTPProbe, ValidationResult

ProbeFunction = Callable[..., HTTPProbe]


def validate_distribution(
    distribution: DistributionCandidate,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_sample_bytes: int = DEFAULT_CONFIG.max_sample_bytes,
    probe: ProbeFunction | None = None,
) -> ValidationResult:
    probe = probe or probe_url
    head_probe = probe(distribution.url, method="HEAD", timeout=timeout, max_bytes=0)
    selected_probe = head_probe

    if _needs_partial_get(head_probe):
        selected_probe = probe(
            distribution.url,
            method="GET",
            timeout=timeout,
            max_bytes=max_sample_bytes,
            headers={"Range": f"bytes=0-{max_sample_bytes - 1}"},
        )

    content_type = _header(selected_probe, "content-type")
    content_disposition = _header(selected_probe, "content-disposition")
    content_length = _header(selected_probe, "content-length")
    format_name = _validated_format(distribution, content_type, content_disposition, selected_probe)
    is_html_error = "text/html" in content_type.lower() and distribution.format != "API"
    ok = (
        selected_probe.error == ""
        and selected_probe.status_code is not None
        and 200 <= selected_probe.status_code < 400
        and not is_html_error
    )

    return ValidationResult(
        url=distribution.url,
        final_url=selected_probe.final_url or selected_probe.url,
        format=format_name,
        ok=ok,
        http_status=selected_probe.status_code,
        mime_type=content_type.split(";", 1)[0].strip(),
        size_bytes=_parse_content_length(content_length),
        etag=_header(selected_probe, "etag"),
        last_modified=_header(selected_probe, "last-modified"),
        content_disposition=content_disposition,
        error=selected_probe.error or ("HTML response instead of data" if is_html_error else ""),
    )


def probe_url(
    url: str,
    method: str,
    timeout: float,
    max_bytes: int,
    headers: dict[str, str] | None = None,
) -> HTTPProbe:
    request = Request(url, method=method, headers=headers or {})

    try:
        with open_public_http_url(request, timeout=timeout) as response:
            body_sample = response.read(max_bytes) if max_bytes > 0 else b""
            return HTTPProbe(
                url=url,
                final_url=response.geturl(),
                status_code=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body_sample=body_sample,
            )
    except HTTPError as exception:
        body_sample = exception.read(max_bytes) if max_bytes > 0 else b""
        return HTTPProbe(
            url=url,
            final_url=exception.geturl(),
            status_code=exception.code,
            headers={key.lower(): value for key, value in exception.headers.items()},
            body_sample=body_sample,
            error=str(exception),
        )
    except (TimeoutError, URLError, OSError, ValueError) as exception:
        return HTTPProbe(
            url=url,
            final_url=url,
            status_code=None,
            error=str(exception),
        )


def _needs_partial_get(probe: HTTPProbe) -> bool:
    content_type = _header(probe, "content-type").lower()
    return (
        probe.status_code in {403, 405, 501}
        or (probe.status_code is not None and 200 <= probe.status_code < 400 and not content_type)
        or "text/html" in content_type
    )


def _validated_format(
    distribution: DistributionCandidate,
    content_type: str,
    content_disposition: str,
    probe: HTTPProbe,
) -> str:
    format_from_headers, _ = guess_format(
        probe.final_url or distribution.url,
        mime_type=f"{content_type} {content_disposition}",
    )
    if format_from_headers != "UNKNOWN":
        return format_from_headers

    sample_format = _format_from_body_sample(probe.body_sample)
    if sample_format != "UNKNOWN":
        return sample_format

    return distribution.format


def _format_from_body_sample(sample: bytes) -> str:
    stripped = sample.strip()
    if not stripped:
        return "UNKNOWN"
    if stripped.startswith(b"PK\x03\x04"):
        return "ZIP"
    if stripped.startswith((b"{", b"[")):
        return "JSON"

    try:
        decoded = stripped[:4096].decode("utf-8")
    except UnicodeDecodeError:
        return "UNKNOWN"

    first_line = decoded.splitlines()[0] if decoded.splitlines() else ""
    if "," in first_line:
        return "CSV"
    if "\t" in first_line:
        return "TSV"

    return "UNKNOWN"


def _header(probe: HTTPProbe, name: str) -> str:
    return probe.headers.get(name.lower(), "")


def _parse_content_length(value: str) -> int | None:
    if not value or not re.fullmatch(r"\d+", value.strip()):
        return None
    return int(value)
