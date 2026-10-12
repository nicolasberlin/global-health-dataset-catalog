"""Bounded record transport that preserves HTTP evidence before normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request

from collector.budget import check_collection_budget, read_with_budget
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.config import DEFAULT_CONFIG
from collector.fetch import open_public_http_url


@dataclass(frozen=True)
class JsonResponse:
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    payload: dict | list


def fetch_record_json(
    url: str,
    *,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_bytes: int = 5_000_000,
    user_agent: str = DEFAULT_CONFIG.user_agent,
) -> JsonResponse:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    status, final_url = None, ""
    try:
        with open_public_http_url(request, timeout=timeout) as response:
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            body = read_with_budget(response, max_bytes + 1)
    except HTTPError as exc:
        check_collection_budget()
        if exc.fp is not None:
            exc.fp.close()
        raise CollectionTransportError(
            "repository_http_error",
            "fetch",
            http_status=exc.code,
            final_url=exc.geturl(),
        ) from exc
    except (TimeoutError, URLError, OSError) as exc:
        check_collection_budget()
        code = (
            "repository_timeout"
            if (
                isinstance(exc, TimeoutError)
                or isinstance(getattr(exc, "reason", None), TimeoutError)
            )
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
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
