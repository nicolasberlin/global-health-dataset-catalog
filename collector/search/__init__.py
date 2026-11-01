"""Repository metadata search providers, filtering and response contracts."""

from collector.search.filtering import filter_repository_results
from collector.search.models import (
    INVALID_METADATA_MESSAGE,
    MISSING_METADATA_VALUE,
    PROVIDER_UNAVAILABLE_MESSAGE,
    JsonFetcher,
    RepositorySearchProvider,
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
)
from collector.search.providers.datacite import DataCiteRepositorySearchProvider
from collector.search.service import search_repository_metadata

__all__ = [
    "DataCiteRepositorySearchProvider",
    "INVALID_METADATA_MESSAGE",
    "JsonFetcher",
    "MISSING_METADATA_VALUE",
    "PROVIDER_UNAVAILABLE_MESSAGE",
    "RepositorySearchProvider",
    "RepositorySearchResponse",
    "RepositorySearchResult",
    "RepositorySearchWarning",
    "filter_repository_results",
    "search_repository_metadata",
]
