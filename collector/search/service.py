"""Orchestration of repository metadata providers and candidate filtering."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from collector.diagnostics import Diagnostic, PipelineFailure
from collector.observability import emit_event
from collector.search.filtering import filter_repository_results
from collector.search.models import (
    INVALID_METADATA_MESSAGE,
    RepositorySearchProvider,
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
)
from collector.search.providers.datacite import DataCiteRepositorySearchProvider


class RepositorySearchFailure(PipelineFailure, ValueError):
    """Preserve the historical ValueError contract with a structured cause."""


def search_repository_metadata(
    query: str,
    providers: Iterable[RepositorySearchProvider] | None = None,
) -> RepositorySearchResponse:
    """Return transient provider candidates without classifying or saving them.

    Provider calls may perform outbound requests. A provider ``ValueError`` is
    downgraded to a warning when another provider succeeds; if every provider
    fails, this function raises ``ValueError``. Results with invalid titles,
    URLs or text incompatible with UTF-8/PostgreSQL are omitted with a warning.
    """

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
            provider_response = provider.search(normalized_query)
        except ValueError:
            errors.append(provider.name)
            emit_event("repository_search_provider", outcome="failed")
            warnings.append(RepositorySearchWarning(provider=provider.name))
            continue

        successful_provider_count += 1
        warnings.extend(provider_response.warnings)
        results.extend(
            replace(result, search_query=normalized_query)
            for result in provider_response.results
        )

    if successful_provider_count == 0 and errors:
        raise RepositorySearchFailure("All repository providers failed.",
                                      diagnostics=[Diagnostic("repository_unavailable", "search")])

    filtered_results, rejected_result_count = filter_repository_results(results)
    if rejected_result_count:
        warnings.append(RepositorySearchWarning(message=INVALID_METADATA_MESSAGE,
                                                code="invalid_repository_metadata"))

    return RepositorySearchResponse(results=filtered_results, warnings=warnings)
