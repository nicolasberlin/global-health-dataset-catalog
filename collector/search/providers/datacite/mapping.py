"""Transform DataCite response entries into internal repository search results."""

from __future__ import annotations

from collector.extraction.errors import ExtractionError
from collector.search.filtering import _http_url, _text
from collector.search.models import RepositorySearchResult
from collector.search.providers.datacite.metadata import (
    _date,
    _description,
    _doi,
    _publisher,
    _search_result_metadata,
    _subjects,
    _title,
)


def _map_search_results(
    data: dict[str, object],
) -> tuple[list[RepositorySearchResult], bool]:
    """Preserve usable result order and report whether any metadata was omitted."""
    items = data.get("data")
    if not isinstance(items, list):
        raise ValueError("Invalid DataCite response shape: expected data list.")

    results: list[RepositorySearchResult] = []
    omitted = False
    for item in items:
        if not isinstance(item, dict):
            omitted = True
            continue

        try:
            result = _datacite_result(item)
        except ExtractionError:
            omitted = True
            continue
        if result is None:
            omitted = True
            continue
        results.append(result)

    return results, omitted


def _datacite_result(item: dict[object, object]) -> RepositorySearchResult | None:
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return None

    doi = _doi(item, attributes)
    url = _http_url(_text(attributes.get("url"))) or _doi_url(doi)
    extracted_title = _title(attributes)
    title = extracted_title or url
    if not title or not url:
        return None

    description = _description(attributes)
    date = _date(attributes)
    keywords = _subjects(attributes)

    return RepositorySearchResult(
        title=title,
        description=description,
        url=url,
        source="DataCite",
        publisher=_publisher(attributes),
        date=date,
        doi=doi,
        keywords=keywords,
        metadata=_search_result_metadata(
            attributes,
            title=extracted_title,
            url=url,
            date=date,
            description=description,
            subjects=keywords,
        ),
    )


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""
