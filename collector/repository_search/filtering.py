from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from urllib.parse import urlsplit

from collector.repository_search.models import RepositorySearchResult


def filter_repository_results(
    results: Iterable[RepositorySearchResult],
) -> tuple[list[RepositorySearchResult], int]:
    filtered_results: list[RepositorySearchResult] = []
    rejected_result_count = 0
    for result in results:
        title = _text(result.title)
        url = _http_url(_text(result.url))
        if not title or not url:
            rejected_result_count += 1
            continue

        filtered_results.append(
            replace(
                result,
                title=title,
                url=url,
            )
        )

    return filtered_results, rejected_result_count


def _http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.hostname:
        return value
    return ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
