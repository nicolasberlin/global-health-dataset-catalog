"""Shared local-first discovery and candidate preparation, without HTTP lifecycle state."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol, TypedDict

from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.db.catalog.search import normalize_dataset_search_query, search_collected_datasets
from app.policies.quotas import WorkAdmission
from collector.classification.repository import (
    MAX_REPOSITORY_DATE_CHARS,
    MAX_REPOSITORY_DESCRIPTION_CHARS,
    MAX_REPOSITORY_DOI_CHARS,
    MAX_REPOSITORY_KEYWORD_CHARS,
    MAX_REPOSITORY_KEYWORDS,
    MAX_REPOSITORY_METADATA_BYTES,
    MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS,
    MAX_REPOSITORY_METADATA_VALUE_CHARS,
    MAX_REPOSITORY_PUBLISHER_CHARS,
    MAX_REPOSITORY_SEARCH_QUERY_CHARS,
    MAX_REPOSITORY_SOURCE_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
)
from collector.diagnostics import Diagnostic
from collector.extraction.dataset_metadata import normalize_dataset_metadata
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
)
from collector.repository_search.filtering import filter_repository_results
from collector.storage.models import CollectedDataset

_REPOSITORY_URL_ADAPTER = TypeAdapter(HttpUrl)


class SearchWarningRecord(TypedDict):
    """Controlled warning fields persisted with the discovery outcome."""

    code: str
    provider: str | None
    message: str
    incomplete: bool


class RepositoryResultBounder(Protocol):
    """Candidate preparation callable with a server-owned relevance query."""

    def __call__(
        self,
        item: RepositorySearchResult,
        *,
        search_query: str,
    ) -> RepositorySearchResult: ...


@dataclass(frozen=True)
class DiscoveryResult:
    """Prepared discovery data and warnings, before atomic publication.

    Local results use ``datasets``; online discovery uses ``candidates``.
    Completeness describes the configured exploration scope, not later
    classification or collection outcomes.
    """

    origin: Literal["database", "online"]
    datasets: list[CollectedDataset] = field(default_factory=list)
    candidates: list[RepositorySearchResult] = field(default_factory=list)
    warnings: list[RepositorySearchWarning] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Only inconclusive warnings prevent discovery within its scope completing."""
        return not any(warning.incomplete for warning in self.warnings)

    @property
    def diagnostics(self) -> list[dict[str, object]]:
        """Build controlled diagnostics without exposing provider warning messages."""
        return [
            Diagnostic(
                warning.code, "search", recovery="manual" if warning.incomplete else "none"
            ).to_dict()
            for warning in self.warnings
        ]

    @property
    def warning_records(self) -> list[SearchWarningRecord]:
        """Persist warning provenance with messages rebuilt from stable codes."""
        return [
            {
                "code": warning.code,
                "provider": warning.provider,
                "message": Diagnostic(warning.code, "search").message,
                "incomplete": warning.incomplete,
            }
            for warning in self.warnings
        ]


async def lookup_local(
    query: str,
    *,
    lookup: Callable[[str], Awaitable[list[CollectedDataset]]] = search_collected_datasets,
) -> list[CollectedDataset]:
    """Search the catalog after removing generic terms.

    Return an empty list without querying the database if no meaningful terms
    remain. Lookup failures propagate to the worker instead of triggering an
    online search.
    """
    local_query = normalize_dataset_search_query(query)
    return await lookup(local_query) if local_query else []


def _bounded_repository_result(
    item: RepositorySearchResult,
    *,
    search_query: str,
) -> RepositorySearchResult:
    """Apply the API trust-boundary limits before provider metadata is stored."""

    data = asdict(item)
    data["title"] = str(data.get("title", ""))[:MAX_REPOSITORY_TITLE_CHARS]
    data["description"] = str(data.get("description", ""))[:MAX_REPOSITORY_DESCRIPTION_CHARS]
    data["source"] = str(data.get("source", ""))[:MAX_REPOSITORY_SOURCE_CHARS]
    data["search_query"] = search_query[:MAX_REPOSITORY_SEARCH_QUERY_CHARS]
    data["publisher"] = str(data.get("publisher", ""))[:MAX_REPOSITORY_PUBLISHER_CHARS]
    data["date"] = str(data.get("date", ""))[:MAX_REPOSITORY_DATE_CHARS]
    data["doi"] = str(data.get("doi", ""))[:MAX_REPOSITORY_DOI_CHARS]
    data["keywords"] = [
        str(keyword)[:MAX_REPOSITORY_KEYWORD_CHARS]
        for keyword in data.get("keywords", [])[:MAX_REPOSITORY_KEYWORDS]
    ]
    data["metadata"] = _bounded_repository_metadata(data.get("metadata"))
    # Provider decisions are untrusted; classification runs later against the server query.
    data["classification"] = None
    return RepositorySearchResult(**data)


def _bounded_repository_metadata(value: object) -> dict[str, str]:
    """Keep the ten classifier fields within character and serialized byte limits."""
    metadata = normalize_dataset_metadata(value if isinstance(value, dict) else {})
    bounded_metadata = {
        key: text[
            : (
                MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS
                if key == "Description of dataset"
                else MAX_REPOSITORY_METADATA_VALUE_CHARS
            )
        ]
        for key, text in metadata.items()
    }

    # UTF-8 and JSON escaping can exceed the byte cap even after character limits.
    while _json_size_bytes(bounded_metadata) > MAX_REPOSITORY_METADATA_BYTES:
        largest_key = max(bounded_metadata, key=lambda key: len(bounded_metadata[key]))
        largest_value = bounded_metadata[largest_key]
        if not largest_value:
            break
        bounded_metadata[largest_key] = largest_value[: len(largest_value) // 2]

    return bounded_metadata


def _json_size_bytes(value: dict[str, str]) -> int:
    """Measure the same compact UTF-8 JSON representation checked by the public API."""
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def prepare_repository_candidates(
    response: RepositorySearchResponse,
    query: str,
    admission: WorkAdmission,
    *,
    bound: RepositoryResultBounder = _bounded_repository_result,
) -> DiscoveryResult:
    """Validate, bound and deduplicate candidates before applying the admission cap.

    Invalid records make discovery incomplete while valid neighbors survive.
    A candidate cap limits the exploration scope without making checks inside
    that scope inconclusive. Existing provider warnings are preserved.
    """
    # Recheck the shared constraints here so direct provider responses cannot bypass admission.
    valid_results, rejected_count = filter_repository_results(response.results)
    candidates = []
    for item in valid_results:
        try:
            # Use the public API's parser without replacing the original URL: its
            # encoded Unicode path can be longer than the accepted input limit.
            _REPOSITORY_URL_ADAPTER.validate_python(item.url)
        except ValidationError:
            rejected_count += 1
            continue
        candidates.append(bound(item, search_query=query))
    warnings = list(response.warnings)
    if rejected_count:
        warnings.append(RepositorySearchWarning(code="invalid_repository_metadata"))
    # Deduplicate before admission: keep the first position with the last duplicate's content.
    candidates = list({(item.source.strip(), item.url): item for item in candidates}.values())
    if admission.max_candidates is not None and len(candidates) > admission.max_candidates:
        candidates = candidates[: admission.max_candidates]
        warnings.append(
            RepositorySearchWarning(
                message=f"Analysis is limited to {admission.max_candidates} datasets per search.",
                code="search_scope_limited",
                # The configured scope is smaller, but checks within it may still conclude.
                incomplete=False,
            )
        )
    return DiscoveryResult("online", candidates=candidates, warnings=warnings)
