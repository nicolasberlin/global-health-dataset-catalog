"""Bounded network validation of discovered distribution candidates."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
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
    if code == 401:
        return "restricted", "Authentication or access permission is required."
    if code in {404, 410}:
        return "unavailable", "Resource was not found at this URL."
    forbidden: tuple[ValidationStatus, str] = (
        "unconfirmed",
        "HTTP 403 refused the check without explicit authentication or permission requirements.",
    )
    if code == 403 and re.match(
        r"(?:basic|bearer|digest|negotiate)\b", _header(probe, "www-authenticate"), re.I,
    ):
        return "restricted", "The server explicitly requests authentication."
    # HTTPError populates error for 403 too; inspect its bounded body before deciding.
    if code != 403 and (probe.error or code is None or not 200 <= code < 300):
        return "unconfirmed", "The request did not confirm access to data."
    sample = probe.body_sample.strip()
    if code in {204, 205} or not sample:
        return forbidden if code == 403 else ("unconfirmed", "No data content was returned.")

    content_type = _header(probe, "content-type").lower()
    text = sample[:8192].decode("utf-8-sig", errors="replace").lower()
    if "html" in content_type or (text.lstrip().startswith("<") and re.search(
        r"<(?:!doctype\s+html|html|head|body|form)\b", text,
    )):
        page = _AccessPage()
        try:
            page.feed(text)
        except (AssertionError, NotImplementedError):
            return (
                "unconfirmed", "The HTML response could not be interpreted to confirm data access.",
            )
        if page.password_form:
            return "restricted", "A login form requires authentication before data can be checked."
        barrier = _access_barrier(" ".join(page.text))
        if not barrier and page.captcha_widget:
            barrier = _access_barrier("captcha")
        if barrier:
            return barrier
        return forbidden if code == 403 else ("unconfirmed", "HTML was returned instead of data.")

    if "json" in content_type or format_name == "JSON" or sample.startswith((b"{", b"[")):
        truncated = _sample_is_truncated(probe)
        if code == 206 and not _prefix_range(probe):
            return "unconfirmed", "The JSON response is not a confirmed initial byte range."
        try:
            payload = read_json_prefix(probe.body_sample) if truncated else json.loads(sample)
        except (ValueError, UnicodeError, RecursionError):
            # A bounded/ranged sample may end in the middle of a valid document.
            if code == 403:
                return forbidden
            return "unconfirmed", "The JSON sample is incomplete or invalid."
        if isinstance(payload, dict):
            failure = (
                bool(payload.get("error")) or bool(payload.get("errors"))
                or payload.get("success") is False
                or str(payload.get("status", "")).lower() in {"error", "failed", "failure"}
            )
            error_fields = {"error", "errors", "message", "detail", "status"}
            if failure or code == 403 or payload.keys() <= error_fields:
                # Data records mentioning login/API keys are not authentication errors.
                error_text = json.dumps({key: value for key, value in payload.items()
                                         if key in error_fields}).lower()
                barrier = _access_barrier(error_text)
                if barrier:
                    return barrier
            if code == 403:
                return forbidden
            if failure:
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
        if code == 403:
            return forbidden
        if not isinstance(payload, (dict, list)) or not payload:
            return "unconfirmed", "The JSON response contains no confirmed data."
        return "available", (
            "JSON data was confirmed in a partial sample; the full document was not validated."
            if truncated else "A JSON data response was confirmed."
        )

    if code == 403:
        return _access_barrier(text) or forbidden
    if format_name in {"UNKNOWN", "API"}:
        return "unconfirmed", "The response format could not be confirmed."
    return "available", "A non-empty data response was confirmed."


def _access_barrier(text: str) -> tuple[ValidationStatus, str] | None:
    """Require affirmative access evidence, not a generic denial or keyword mention."""
    text = re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", text.lower()))
    if re.search(
        r"\b(?:unauthori[sz]ed|unauthenticated)\b"
        r"|\b(?:authentication|authorization|authorisation|login|log in|sign in|permissions?)"
        r" (?:is |are )?required\b"
        r"|\bauthentication (?:has )?failed\b"
        r"|\brequires (?:authentication|authorization|authorisation|permissions?)\b"
        r"|\b(?:please|must|need to) (?:log in|sign in|authenticate)\b"
        r"|\b(?:missing|invalid|expired|required) (?:api key|access token|credentials)\b"
        r"|\b(?:api key|access token|credentials) (?:is |are )?"
        r"(?:required|missing|invalid|expired)\b"
        r"|\bauthentication credentials (?:were |are )?not provided\b"
        r"|\b(?:insufficient permissions|permission denied)\b", text,
    ):
        return "restricted", "The response explicitly requires authentication or access permission."
    if re.search(
        r"\bcaptcha\b|\brecaptcha\b|\bhcaptcha\b|\bverify (?:that )?you are (?:a )?human\b"
        r"|\bchecking your browser\b|\b(?:anti bot|bot) (?:challenge|verification)\b", text,
    ):
        return "unconfirmed", "An anti-bot challenge prevented verification of data access."
    return None


class _AccessPage(HTMLParser):
    """Inspect visible text and password forms, ignoring scripts and navigation URLs."""

    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.in_form = False
        self.hidden_depth = 0
        self.password_form = False
        self.captcha_widget = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if self.hidden_depth:
            return
        if tag == "form":
            self.in_form = True
        attributes = dict(attrs)
        self.captcha_widget |= bool(
            {"g-recaptcha", "h-captcha", "cf-turnstile"}
            & set((attributes.get("class") or "").split())
        )
        if tag == "input" and self.in_form:
            self.password_form |= (attributes.get("type") or "").lower() == "password"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        if tag == "form":
            self.in_form = False

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.text.append(data.strip())


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
