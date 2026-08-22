from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Optional, Protocol
from urllib.parse import urlencode, urlsplit

from collector.discovery.adapters import fetch_json_url
from collector.extraction.extractor import html_to_text

JsonFetcher = Callable[[str], dict[str, object]]
logger = logging.getLogger(__name__)
PROVIDER_UNAVAILABLE_MESSAGE = "This source could not be searched."
INVALID_METADATA_MESSAGE = "Some results were omitted because their metadata was invalid."


@dataclass(frozen=True)
class RepositorySearchResult:
    title: str
    url: str
    source: str
    description: str = ""
    publisher: str = ""
    date: str = ""
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RepositorySearchWarning:
    message: str = PROVIDER_UNAVAILABLE_MESSAGE
    provider: Optional[str] = None  # noqa: UP045 - Keep Python 3.9-compatible typing.


@dataclass(frozen=True)
class RepositorySearchResponse:
    results: list[RepositorySearchResult] = field(default_factory=list)
    warnings: list[RepositorySearchWarning] = field(default_factory=list)


class RepositorySearchProvider(Protocol):
    name: str

    def search(self, query: str) -> list[RepositorySearchResult]:
        ...


class DataCiteRepositorySearchProvider:
    name = "DataCite"
    _base_url = "https://api.datacite.org/dois"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        page_size: int = 10,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._page_size = page_size

    def search(self, query: str) -> list[RepositorySearchResult]:
        data = self._fetch_json(self._search_url(query))
        items = data.get("data")
        if not isinstance(items, list):
            raise ValueError("Invalid DataCite response shape: expected data list.")

        results: list[RepositorySearchResult] = []
        for rank, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            result = _datacite_result(item, rank)
            if result is not None:
                results.append(result)

        return results

    def _search_url(self, query: str) -> str:
        params = {
            "query": query,
            "resource-type-id": "dataset",
            "page[size]": str(self._page_size),
            "sort": "relevance",
        }
        return f"{self._base_url}?{urlencode(params)}"


def search_repository_metadata(
    query: str,
    providers: Iterable[RepositorySearchProvider] | None = None,
) -> RepositorySearchResponse:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Search query is required")

    active_providers = (
        list(providers) if providers is not None else [DataCiteRepositorySearchProvider()]
    )
    results: list[RepositorySearchResult] = []
    errors: list[str] = []
    warnings: list[RepositorySearchWarning] = []
    successful_provider_count = 0

    for provider in active_providers:
        try:
            provider_results = provider.search(normalized_query)
        except ValueError as exception:
            error = f"{provider.name}: {exception}"
            errors.append(error)
            logger.warning("Repository search provider failed: %s", error)
            warnings.append(RepositorySearchWarning(provider=provider.name))
            continue

        successful_provider_count += 1
        results.extend(provider_results)

    if successful_provider_count == 0 and errors:
        raise ValueError("All repository providers failed.")

    filtered_results, rejected_result_count = filter_repository_results(results)
    if rejected_result_count:
        warnings.append(RepositorySearchWarning(message=INVALID_METADATA_MESSAGE))

    return RepositorySearchResponse(
        results=sorted(
            filtered_results,
            key=lambda result: result.relevance_score,
            reverse=True,
        ),
        warnings=warnings,
    )


def filter_repository_results(
    results: Iterable[RepositorySearchResult],
) -> tuple[list[RepositorySearchResult], int]:
    filtered_results: list[RepositorySearchResult] = []
    rejected_result_count = 0
    for result in results:
        title = _text(result.title)
        url = _http_url(_text(result.url))
        relevance_score = _number(result.relevance_score)
        if (
            not title
            or not url
            or relevance_score is None
            or relevance_score < 0
            or relevance_score > 1
        ):
            rejected_result_count += 1
            continue

        filtered_results.append(
            replace(
                result,
                title=title,
                url=url,
                relevance_score=round(relevance_score, 4),
            )
        )

    return filtered_results, rejected_result_count


def _datacite_result(
    item: dict[object, object],
    rank: int,
) -> RepositorySearchResult | None:
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return None

    doi = _doi(item, attributes)
    url = _http_url(_text(attributes.get("url"))) or _doi_url(doi)
    title = _title(attributes) or url
    if not title or not url:
        return None

    native_score = _number(attributes.get("score"))
    if native_score is None:
        native_score = _number(item.get("score"))

    resource_types = attributes.get("types")
    resource_types = resource_types if isinstance(resource_types, dict) else {}

    return RepositorySearchResult(
        title=title,
        description=_description(attributes),
        url=url,
        source="DataCite",
        publisher=_publisher(attributes),
        date=_date(attributes),
        doi=doi,
        keywords=_subjects(attributes),
        relevance_score=_relevance_score(native_score, rank),
        metadata={
            "provider": "datacite",
            "datacite_id": _text(item.get("id")),
            "resource_type": _text(resource_types.get("resourceTypeGeneral")),
            "resource_subtype": _text(resource_types.get("resourceType")),
            "native_score": native_score,
        },
    )


def _title(attributes: dict[object, object]) -> str:
    titles = attributes.get("titles")
    if not isinstance(titles, list):
        return ""

    for title in titles:
        if isinstance(title, dict):
            text = html_to_text(_text(title.get("title")))
            if text:
                return text

    return ""


def _description(attributes: dict[object, object]) -> str:
    descriptions = attributes.get("descriptions")
    if not isinstance(descriptions, list):
        return ""

    fallback = ""
    for description in descriptions:
        if not isinstance(description, dict):
            continue

        text = html_to_text(_text(description.get("description")))
        if not text:
            continue

        if _text(description.get("descriptionType")).lower() == "abstract":
            return text
        if not fallback:
            fallback = text

    return fallback


def _publisher(attributes: dict[object, object]) -> str:
    publisher = attributes.get("publisher")
    if isinstance(publisher, dict):
        return _text(publisher.get("name"))

    return _text(publisher)


def _date(attributes: dict[object, object]) -> str:
    publication_year = attributes.get("publicationYear")
    if isinstance(publication_year, (int, str)):
        return str(publication_year).strip()

    dates = attributes.get("dates")
    if isinstance(dates, list):
        preferred_types = {"issued", "publicationdate", "created", "available"}
        fallback = ""
        for date_item in dates:
            if not isinstance(date_item, dict):
                continue

            date_value = _text(date_item.get("date"))
            if not date_value:
                continue

            date_type = _text(date_item.get("dateType")).replace(" ", "").lower()
            if date_type in preferred_types:
                return date_value
            if not fallback:
                fallback = date_value

        if fallback:
            return fallback

    for key in ("published", "created", "updated"):
        value = _text(attributes.get(key))
        if value:
            return value

    return ""


def _doi(
    item: dict[object, object],
    attributes: dict[object, object],
) -> str:
    doi = _text(attributes.get("doi")) or _text(item.get("id"))
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""


def _http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.hostname:
        return value
    return ""


def _subjects(attributes: dict[object, object]) -> list[str]:
    subjects = attributes.get("subjects")
    if not isinstance(subjects, list):
        return []

    values: list[str] = []
    for subject in subjects:
        if not isinstance(subject, dict):
            continue

        text = html_to_text(_text(subject.get("subject")))
        if text and text not in values:
            values.append(text)

    return values


def _relevance_score(native_score: float | None, rank: int) -> float:
    if native_score is not None and 0 <= native_score <= 1:
        return round(native_score, 4)

    return max(0.0, round(1.0 - (rank * 0.05), 4))


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
