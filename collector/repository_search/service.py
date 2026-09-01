from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace

from collector.classification.repository import RepositoryResultClassifier
from collector.extraction.dataset_metadata import normalize_dataset_metadata
from collector.repository_search.filtering import filter_repository_results
from collector.repository_search.models import (
    INVALID_METADATA_MESSAGE,
    MISSING_METADATA_VALUE,
    RepositorySearchProvider,
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
)
from collector.repository_search.providers.datacite import DataCiteRepositorySearchProvider
from collector.storage.models import PageSnapshot

logger = logging.getLogger(__name__)


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
        results.extend(
            replace(result, search_query=normalized_query)
            for result in provider_results
        )

    if successful_provider_count == 0 and errors:
        raise ValueError("All repository providers failed.")

    filtered_results, rejected_result_count = filter_repository_results(results)
    if rejected_result_count:
        warnings.append(RepositorySearchWarning(message=INVALID_METADATA_MESSAGE))

    return RepositorySearchResponse(results=filtered_results, warnings=warnings)


def classify_repository_result(
    result: RepositorySearchResult,
    classifier: RepositoryResultClassifier,
) -> RepositorySearchResult:
    """Classify one repository result from its normalized metadata contract."""
    classification = classifier.classify(_repository_result_page(result))
    return replace(result, classification=classification)


def _repository_result_page(result: RepositorySearchResult) -> PageSnapshot:
    metadata = normalize_dataset_metadata(result.metadata)
    title = _metadata_text(metadata["Title"], fallback=result.title)
    description = _metadata_text(
        metadata["Description of dataset"],
        fallback=result.description,
    )
    return PageSnapshot(
        url=result.url,
        canonical_url=result.url,
        search_query=result.search_query,
        title=title,
        meta_description=description,
        publisher=result.publisher,
        geography=_metadata_items(metadata["Geography"]),
        date_of_publication=_metadata_text(
            metadata["Date of publication"],
            fallback=result.date,
        ),
        dataset_url=_metadata_text(metadata["Dataset URL"], fallback=result.url),
        diseases=_metadata_items(metadata["Disease(s)"]),
        size_of_dataset=_metadata_text(metadata["Size of dataset"]),
        demographic_information=_metadata_items(
            metadata["Demographic information"]
        ),
        sharing_license=_metadata_text(metadata["Sharing license"]),
        modality_of_data=_metadata_items(metadata["Modality of data"]),
        description_of_dataset=description,
        text=" ".join(
            value
            for value in (result.title, result.description, " ".join(result.keywords))
            if value
        ),
    )


def _metadata_text(value: str, *, fallback: str = "") -> str:
    return fallback if value == MISSING_METADATA_VALUE else value


def _metadata_items(value: str) -> tuple[str, ...]:
    if value == MISSING_METADATA_VALUE:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())
