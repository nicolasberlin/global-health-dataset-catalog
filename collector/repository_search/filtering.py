"""Validation and normalization of repository provider results."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from collector.classification.repository import MAX_REPOSITORY_URL_CHARS
from collector.extraction.dataset_metadata import normalize_dataset_metadata
from collector.repository_search.models import RepositorySearchResult
from collector.url_utils import normalize_http_url


def filter_repository_results(
    results: Iterable[RepositorySearchResult],
) -> tuple[list[RepositorySearchResult], int]:
    """Filter missing titles, oversized URLs and text incompatible with storage.

    Invalid records are counted individually so callers can report incomplete
    discovery without discarding their valid neighbors. Provider search queries
    and classifications are replaced by the server before persistence.
    """

    filtered_results: list[RepositorySearchResult] = []
    rejected_result_count = 0
    for result in results:
        title = _text(result.title)
        url = _http_url(_text(result.url))
        texts = (
            result.title,
            result.url,
            result.source,
            result.description,
            result.publisher,
            result.date,
            result.doi,
            *result.keywords,
            *normalize_dataset_metadata(result.metadata).values(),
        )
        if (
            not title
            or not url
            or len(url) > MAX_REPOSITORY_URL_CHARS
            or not all(_valid_provider_text(text) for text in texts)
        ):
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


def _valid_provider_text(value: str) -> bool:
    """Reject PostgreSQL NUL bytes and text that cannot be encoded as UTF-8."""
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _http_url(value: str) -> str:
    # Validate before URL encoding: an isolated surrogate in a query would raise there.
    if not _valid_provider_text(value):
        return ""
    return normalize_http_url(value) or ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
