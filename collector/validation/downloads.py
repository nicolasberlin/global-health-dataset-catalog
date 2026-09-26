"""Bounded network validation of discovered distribution candidates."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from collector.config import DEFAULT_CONFIG
from collector.extraction.distributions import guess_format
from collector.fetch import open_public_http_url
from collector.storage.models import (
    DistributionCandidate,
    HTTPProbe,
    ValidationResult,
    ValidationStatus,
)
from collector.validation.json_sample import read_json_prefix

ProbeFunction = Callable[..., HTTPProbe]


def validate_distribution(
    distribution: DistributionCandidate,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_sample_bytes: int = DEFAULT_CONFIG.max_sample_bytes,
    probe: ProbeFunction | None = None,
) -> ValidationResult:
    """Normalize one distribution probe into a validation outcome.

    HEAD supplies metadata; a bounded GET sample is required to confirm access.
    Transport failures and ambiguous samples remain unconfirmed.
    """

    if max_sample_bytes < 1:
        raise ValueError("max_sample_bytes must be positive.")
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
    format_name = _validated_format(distribution, content_type, content_disposition, selected_probe)
    status, reason = _response_status(selected_probe, format_name)

    return ValidationResult(
        url=distribution.url,
        final_url=selected_probe.final_url or selected_probe.url,
        format=format_name,
        ok=status == "available",
        status=status,
        reason=reason,
        http_status=selected_probe.status_code,
        mime_type=content_type.split(";", 1)[0].strip(),
        size_bytes=_total_size(selected_probe, head_probe),
        etag=_header(selected_probe, "etag"),
        last_modified=_header(selected_probe, "last-modified"),
        content_disposition=content_disposition,
        error=selected_probe.error or (reason if status != "available" else ""),
    )


def probe_url(
    url: str,
    method: str,
    timeout: float,
    max_bytes: int,
    headers: dict[str, str] | None = None,
) -> HTTPProbe:
    """Perform one bounded probe with public-URL and redirect protection.

    Successful responses retain at most ``max_bytes`` plus read one lookahead
    byte to detect truncation. HTTP, transport, DNS, and
    blocked-destination errors are captured as probe data so distribution
    validation can reject the resource without raising.
    """

    request = Request(url, method=method, headers=headers or {})

    try:
        with open_public_http_url(request, timeout=timeout) as response:
            # One lookahead byte distinguishes a complete body exactly at the
            # limit from a server that ignored Range. Only max_bytes are kept.
            body = response.read(max_bytes + 1) if max_bytes > 0 else b""
            return HTTPProbe(
                url=url,
                final_url=response.geturl(),
                status_code=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body_sample=body[:max_bytes],
                sample_truncated=len(body) > max_bytes,
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
    return (
        probe.status_code in {403, 405, 501}
        or (probe.status_code is not None and 200 <= probe.status_code < 400)
    )


def _response_status(probe: HTTPProbe, format_name: str) -> tuple[ValidationStatus, str]:
    code = probe.status_code
    if code in {401, 403}:
        return "restricted", "Authentication or access permission is required."
    if code in {404, 410}:
        return "unavailable", "Resource was not found at this URL."
    if probe.error or code is None or not 200 <= code < 300:
        return "unconfirmed", "The request did not confirm access to data."
    sample = probe.body_sample.strip()
    if code in {204, 205} or not sample:
        return "unconfirmed", "No data content was returned."

    content_type = _header(probe, "content-type").lower()
    text = sample[:8192].decode("utf-8-sig", errors="replace").lower()
    if "html" in content_type or (text.lstrip().startswith("<") and re.search(
        r"<(?:!doctype\s+html|html|head|body|form)\b", text,
    )):
        if re.search(r"captcha|type\s*=\s*['\"]?password\b|\blog[ -]?in\b|\bsign[ -]?in\b", text):
            return "restricted", "A login page or CAPTCHA prevents access to data."
        return "unconfirmed", "HTML was returned instead of data."

    if "json" in content_type or format_name == "JSON" or sample.startswith((b"{", b"[")):
        truncated = _sample_is_truncated(probe)
        if code == 206 and not _prefix_range(probe):
            return "unconfirmed", "The JSON response is not a confirmed initial byte range."
        try:
            payload = read_json_prefix(probe.body_sample) if truncated else json.loads(sample)
        except (ValueError, UnicodeError, RecursionError):
            # A bounded/ranged sample may end in the middle of a valid document.
            return "unconfirmed", "The JSON sample is incomplete or invalid."
        if isinstance(payload, dict):
            failure = (
                bool(payload.get("error")) or bool(payload.get("errors"))
                or payload.get("success") is False
                or str(payload.get("status", "")).lower() in {"error", "failed", "failure"}
            )
            if failure:
                error_text = json.dumps(payload).lower()
                if re.search(
                    r"authenticat|unauthori[sz]ed|forbidden|api[ _-]?key|captcha|log[ -]?in"
                    r"|access denied", error_text,
                ):
                    return "restricted", "The API requires authentication or access permission."
                return "unconfirmed", "The API returned an error response."
            # Common data envelopes and plain records; metadata alone is insufficient.
            for key in ("data", "results", "records", "value", "items", "features"):
                if key in payload:
                    payload = payload[key]
                    break
            else:
                metadata_keys = {"error", "errors", "success", "status", "message", "detail",
                                 "count", "total", "links", "meta", "metadata"}
                payload = {key: value for key, value in payload.items() if key not in metadata_keys}
        if not isinstance(payload, (dict, list)) or not payload:
            return "unconfirmed", "The JSON response contains no confirmed data."
        return "available", (
            "JSON data was confirmed in a partial sample; the full document was not validated."
            if truncated else "A JSON data response was confirmed."
        )

    if format_name in {"UNKNOWN", "API"}:
        return "unconfirmed", "The response format could not be confirmed."
    return "available", "A non-empty data response was confirmed."


def _prefix_range(probe: HTTPProbe) -> re.Match | None:
    match = re.fullmatch(r"bytes 0-(\d+)/(\d+|\*)", _header(probe, "content-range"))
    if match:
        end, total = match.groups()
        end_number = _parse_content_length(end)
        total_number = _parse_content_length(total)
        if (end_number is not None
                and (end_number + 1 == len(probe.body_sample)
                     or (probe.sample_truncated and end_number + 1 > len(probe.body_sample)))
                and (total == "*" or (total_number is not None and end_number < total_number))):
            return match
    return None


def _sample_is_truncated(probe: HTTPProbe) -> bool:
    if probe.sample_truncated:
        return True
    if probe.status_code == 206:
        match = _prefix_range(probe)
        if match:
            _, total = match.groups()
            return total == "*" or int(total) > len(probe.body_sample)
    return False


def _total_size(probe: HTTPProbe, head: HTTPProbe) -> int | None:
    if probe.status_code == 206:
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", _header(probe, "content-range"))
        if match:
            start, end, total = (_parse_content_length(value) for value in match.groups())
            if start is not None and end is not None and total is not None and start <= end < total:
                return total
    if probe.status_code == 200:
        length = _parse_content_length(_header(probe, "content-length"))
        if length is not None:
            return length
    # Do not use HEAD metadata from a login page, a different representation or an error.
    if (head.status_code == 200 and not head.error and head.final_url == probe.final_url
            and "html" not in _header(head, "content-type").lower()
            and all(not _header(head, key) or not _header(probe, key)
                    or _header(head, key) == _header(probe, key)
                    for key in ("etag", "content-type", "content-encoding"))):
        length = _parse_content_length(_header(head, "content-length"))
        if length is not None and length >= len(probe.body_sample):
            return length
    return None


def _validated_format(
    distribution: DistributionCandidate,
    content_type: str,
    content_disposition: str,
    probe: HTTPProbe,
) -> str:
    """Prefer response metadata, then sampled bytes, then the discovered format."""

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
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,19}", value):
        return None
    length = int(value)
    return length if length <= 2**63 - 1 else None
