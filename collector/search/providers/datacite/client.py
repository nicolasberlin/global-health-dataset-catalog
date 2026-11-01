"""DataCite API requests and public search-response orchestration."""

from __future__ import annotations

from urllib.parse import urlencode

from collector.network.json import fetch_json_url
from collector.search.models import (
    INVALID_METADATA_MESSAGE,
    JsonFetcher,
    RepositorySearchResponse,
    RepositorySearchWarning,
)
from collector.search.providers.datacite.mapping import _map_search_results


class DataCiteRepositorySearchProvider:
    """Search DataCite datasets and map records to the repository contract."""

    name = "DataCite"
    _base_url = "https://api.datacite.org/dois"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        page_size: int = 10,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._page_size = page_size

    def search(self, query: str) -> RepositorySearchResponse:
        data = self._fetch_json(self._search_url(query))
        results, omitted = _map_search_results(data)

        warnings = [
            RepositorySearchWarning(
                code="invalid_repository_metadata",
                message=INVALID_METADATA_MESSAGE,
                provider=self.name,
            )
        ] if omitted else []
        return RepositorySearchResponse(results=results, warnings=warnings)

    def _search_url(self, query: str) -> str:
        params = {
            "query": query,
            "resource-type-id": "dataset",
            "page[size]": str(self._page_size),
            "sort": "relevance",
        }
        return f"{self._base_url}?{urlencode(params)}"
