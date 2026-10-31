"""Bounded public JSON fetching with effective document URLs."""

from __future__ import annotations

from contextlib import nullcontext
from urllib.error import HTTPError, URLError
from urllib.request import Request

from collector.budget import check_collection_budget, read_with_budget
from collector.config import DEFAULT_CONFIG
from collector.network.fetch import decode_json_body, open_public_http_url


class JsonDocument(dict[str, object]):
    """JSON object with its effective document URL for relative links and evidence."""

    def __init__(self, payload: dict[str, object], final_url: str) -> None:
        super().__init__(payload)
        self.final_url = final_url


def document_url(payload: dict[str, object], requested_url: str) -> str:
    return payload.final_url if isinstance(payload, JsonDocument) else requested_url


def fetch_json_url(
    url: str,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_bytes: int = 5_000_000,
    user_agent: str = DEFAULT_CONFIG.user_agent,
    *,
    allow_list: bool = False,
) -> dict[str, object] | list:
    """Fetch bounded public JSON; collection may explicitly allow file-metadata lists."""

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
        method="GET",
    )

    try:
        with open_public_http_url(request, timeout=timeout) as response:
            body = read_with_budget(response, max_bytes + 1)
            final_url = response.geturl() if hasattr(response, "geturl") else url
    except HTTPError as exception:
        with exception if exception.fp is not None else nullcontext():
            check_collection_budget()
            raise ValueError(f"JSON URL returned HTTP {exception.code}.") from exception
    except (TimeoutError, URLError, OSError) as exception:
        check_collection_budget()
        raise ValueError(f"Could not fetch JSON URL: {exception}") from exception

    if len(body) > max_bytes:
        raise ValueError("JSON response is too large for discovery.")

    data = decode_json_body(body)
    if not isinstance(data, dict) and not (allow_list and isinstance(data, list)):
        raise ValueError("JSON URL did not return an object.")

    return JsonDocument(data, final_url) if isinstance(data, dict) else data
