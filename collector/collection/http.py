"""Bounded record transport that preserves HTTP evidence before normalization."""

from __future__ import annotations

import errno
import socket
import ssl
import time
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request

from collector.budget import active_collection_budget, check_collection_budget, read_with_budget
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.diagnostics import retry_after
from collector.fetch import decode_json_body, is_timeout_error, open_public_http_url
from collector.observability import emit_event

RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class JsonResponse:
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    payload: dict | list
    request_attempts: int = 1


def fetch_record_json(
    url: str,
    *,
    timeout: float = DEFAULT_CONFIG.record_request_timeout_seconds,
    max_bytes: int = 5_000_000,
    user_agent: str = DEFAULT_CONFIG.user_agent,
    max_attempts: int = DEFAULT_CONFIG.record_max_attempts,
    max_retry_wait: float = DEFAULT_CONFIG.record_retry_max_wait_seconds,
) -> JsonResponse:
    """Retry idempotent metadata reads only, within the existing collection budget.

    Invalid payloads, access refusals and certificate/policy failures are not
    retryable. A provider delay exceeding our wait limit is preserved for manual
    recovery instead of being shortened.
    """
    # Reuse configuration validation for direct transport callers too.
    CollectorConfig(
        record_request_timeout_seconds=timeout, record_max_attempts=max_attempts,
        record_retry_max_wait_seconds=max_retry_wait,
    )
    for number in range(1, max_attempts + 1):
        check_collection_budget()
        try:
            result = _fetch_record_json_once(
                url, timeout=timeout, max_bytes=max_bytes, user_agent=user_agent,
            )
            return replace(result, request_attempts=number)
        except CollectionResponseError as exc:
            exc.request_attempts = number
            raise
        except CollectionTransportError as exc:
            exc.request_attempts = number
            exc.diagnostics = [replace(
                item, attempt=number, max_attempts=max_attempts,
            ) for item in exc.diagnostics]
            cause = exc.__cause__
            retryable = (
                cause.code in RETRYABLE_HTTP_STATUSES
                if isinstance(cause, HTTPError) else _transient_network_error(cause)
            )
            if number == max_attempts or not retryable:
                raise
            delay = float(2 ** (number - 1))
            date = exc.diagnostics[0].retry_at
            if date:
                delay = max(delay, (
                    datetime.fromisoformat(date) - datetime.now(timezone.utc)
                ).total_seconds())
            budget = active_collection_budget()
            if delay > max_retry_wait or (budget and delay >= budget.remaining()):
                raise
            emit_event(
                "record_request_retry", outcome=exc.diagnostics[0].code,
                retry_count=number, delay_seconds=delay,
            )
            time.sleep(delay)
            check_collection_budget()


def _transient_network_error(exc: Exception | None) -> bool:
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLError):
        return False  # Never mask TLS/certificate failures with retries.
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return isinstance(reason, (TimeoutError, socket.timeout, ConnectionError)) or (
        isinstance(reason, OSError) and reason.errno in {
            errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNREFUSED,
            errno.ECONNABORTED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPIPE,
        }
    )


def _fetch_record_json_once(url, *, timeout, max_bytes, user_agent) -> JsonResponse:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    status, final_url = None, ""
    try:
        with open_public_http_url(request, timeout=timeout) as response:
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            body = read_with_budget(response, max_bytes + 1)
    except HTTPError as exc:
        with exc if exc.fp is not None else nullcontext():
            check_collection_budget()
        error = CollectionTransportError(
            "repository_http_error",
            "fetch",
            http_status=exc.code,
            final_url=exc.geturl(),
        )
        date = retry_after((exc.headers or {}).get("Retry-After"))
        if date:
            error.diagnostics = [replace(item, retry_at=date) for item in error.diagnostics]
        raise error from exc
    except (TimeoutError, URLError, OSError) as exc:
        check_collection_budget()
        code = (
            "repository_timeout"
            if is_timeout_error(exc)
            else "repository_network_error"
        )
        raise CollectionTransportError(
            code, "fetch", http_status=status, final_url=final_url,
        ) from exc
    if len(body) > max_bytes:
        raise CollectionResponseError(
            "repository_response_too_large",
            "decode",
            http_status=status,
            final_url=final_url,
        )
    try:
        payload = decode_json_body(body)
    except ValueError as exc:
        raise CollectionResponseError(
            "repository_invalid_json",
            "decode",
            http_status=status,
            final_url=final_url,
        ) from exc
    if not isinstance(payload, (dict, list)):
        raise CollectionResponseError(
            "repository_invalid_json",
            "decode",
            http_status=status,
            final_url=final_url,
        )
    return JsonResponse(url, final_url, status, content_type, payload)
