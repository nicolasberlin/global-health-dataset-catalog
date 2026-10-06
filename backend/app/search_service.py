"""Shared local-first discovery and candidate preparation, without HTTP lifecycle state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from app.db.collected_datasets import normalize_dataset_search_query, search_collected_datasets
from app.quota_policy import WorkAdmission
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
from collector.storage.models import CollectedDataset


@dataclass(frozen=True)
class DiscoveryResult:
    origin: str
    datasets: list[CollectedDataset] = field(default_factory=list)
    candidates: list[RepositorySearchResult] = field(default_factory=list)
    warnings: list[RepositorySearchWarning] = field(default_factory=list)

    @property
    def complete(self):
        return not any(warning.incomplete for warning in self.warnings)

    @property
    def diagnostics(self):
        return [
            Diagnostic(
                warning.code, "search", recovery="manual" if warning.incomplete else "none"
            ).to_dict()
            for warning in self.warnings
        ]

    @property
    def warning_records(self):
        return [
            {
                "code": warning.code,
                "provider": warning.provider,
                "message": Diagnostic(warning.code, "search").message,
                "incomplete": warning.incomplete,
            }
            for warning in self.warnings
        ]


async def lookup_local(query, *, lookup=search_collected_datasets):
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
    data["classification"] = None
    return RepositorySearchResult(**data)


def _bounded_repository_metadata(value: object) -> dict[str, str]:
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

    while _json_size_bytes(bounded_metadata) > MAX_REPOSITORY_METADATA_BYTES:
        largest_key = max(bounded_metadata, key=lambda key: len(bounded_metadata[key]))
        largest_value = bounded_metadata[largest_key]
        if not largest_value:
            break
        bounded_metadata[largest_key] = largest_value[: len(largest_value) // 2]

    return bounded_metadata


def _json_size_bytes(value: dict[str, str]) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def prepare_online(
    response: RepositorySearchResponse,
    query: str,
    admission: WorkAdmission,
    *,
    bound=_bounded_repository_result,
) -> DiscoveryResult:
    candidates = [bound(item, search_query=query) for item in response.results]
    candidates = list({(item.source.strip(), item.url): item for item in candidates}.values())
    warnings = list(response.warnings)
    if admission.max_candidates is not None and len(candidates) > admission.max_candidates:
        candidates = candidates[: admission.max_candidates]
        warnings.append(
            RepositorySearchWarning(
                message=f"Analysis is limited to {admission.max_candidates} datasets per search.",
                code="search_scope_limited",
                incomplete=False,
            )
        )
    return DiscoveryResult("online", candidates=candidates, warnings=warnings)
