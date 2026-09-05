"""Data contracts for repository metadata search providers and responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional, Protocol

from collector.classification.repository import RepositoryClassification
from collector.extraction.dataset_metadata import MISSING_DATASET_METADATA_VALUE

JsonFetcher = Callable[[str], dict[str, object]]

PROVIDER_UNAVAILABLE_MESSAGE = "This source could not be searched."
INVALID_METADATA_MESSAGE = "Some results were omitted because their metadata was invalid."
MISSING_METADATA_VALUE = MISSING_DATASET_METADATA_VALUE


@dataclass(frozen=True)
class RepositorySearchResult:
    """Provider-normalized candidate returned by repository search.

    ``url`` is the dataset landing page rather than a validated distribution.
    ``search_query`` preserves the user query for the later relevance check,
    ``metadata`` carries the normalized classifier contract, and
    ``classification`` remains absent until that check completes.
    """

    title: str
    url: str
    source: str
    search_query: str = ""
    description: str = ""
    publisher: str = ""
    date: str = ""
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    classification: RepositoryClassification | None = None


@dataclass(frozen=True)
class RepositorySearchWarning:
    """Non-fatal provider or metadata problem exposed with search results."""

    message: str = PROVIDER_UNAVAILABLE_MESSAGE
    provider: Optional[str] = None  # noqa: UP045 - Keep Python 3.9-compatible typing.


@dataclass(frozen=True)
class RepositorySearchResponse:
    """Repository results together with non-fatal search warnings."""

    results: list[RepositorySearchResult] = field(default_factory=list)
    warnings: list[RepositorySearchWarning] = field(default_factory=list)


class RepositorySearchProvider(Protocol):
    """Interface implemented by external repository search providers."""

    name: str

    def search(self, query: str) -> list[RepositorySearchResult]:
        ...
