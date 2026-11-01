"""LLM-backed relevance classification for repository search results."""

from __future__ import annotations

from typing import cast

from collector.classification.relevance.models import (
    MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS,
    MAX_REPOSITORY_MISSING_INFORMATION_CHARS,
    MAX_REPOSITORY_MISSING_INFORMATION_ITEMS,
    REPOSITORY_RELEVANCE_LABELS,
    RepositoryClassification,
    RepositoryRelevanceLabel,
)
from collector.llm.classifier import BaseLLMClassifier
from collector.llm.errors import ClassificationError
from collector.models import PageSnapshot
from collector.search.limits import (
    MAX_REPOSITORY_PUBLISHER_CHARS,
    MAX_REPOSITORY_SEARCH_QUERY_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
)

# PageSnapshot permits larger values; these tighter limits keep prompts bounded.
MAX_REPOSITORY_LLM_DESCRIPTION_CHARS = 6_000
MAX_REPOSITORY_LLM_METADATA_VALUE_CHARS = 1_500
MAX_REPOSITORY_LLM_TEXT_CHARS = 4_000
MAX_REPOSITORY_LLM_URL_CHARS = 2_048


class LLMRepositoryRelevanceClassifier(BaseLLMClassifier[RepositoryClassification]):
    """Classify a repository candidate against the original user query.

    Only bounded provider metadata is sent. A valid relevance label produces a
    decision, while missing queries, provider failures, and malformed or
    inconsistent responses raise ``ClassificationError``.
    """

    failure_message = "LLM repository relevance classification failed."

    def classify(self, page: PageSnapshot) -> RepositoryClassification:
        payload = _build_repository_relevance_payload(page)

        return self._classify_payload(payload)

    def _parse_response(self, response: dict[str, object]) -> RepositoryClassification:
        return _parse_repository_relevance_classification(response)


def _build_repository_relevance_payload(page: PageSnapshot) -> dict[str, object]:
    if not page.search_query:
        raise ClassificationError(
            "Search query is required for repository relevance classification.",
            code="llm_invalid_response",
        )

    metadata = {
        key: _repository_metadata_value(key, value)
        for key, value in page.dataset_metadata().items()
    }
    return {
        "search_query": page.search_query[:MAX_REPOSITORY_SEARCH_QUERY_CHARS],
        "dataset_metadata": metadata,
        "repository_result": {
            "url": page.url[:MAX_REPOSITORY_LLM_URL_CHARS],
            "canonical_url": page.canonical_url[:MAX_REPOSITORY_LLM_URL_CHARS],
            "title": page.title[:MAX_REPOSITORY_TITLE_CHARS],
            "description": page.description_of_dataset[:MAX_REPOSITORY_LLM_DESCRIPTION_CHARS],
            "publisher": page.publisher[:MAX_REPOSITORY_PUBLISHER_CHARS],
            "text": page.text[:MAX_REPOSITORY_LLM_TEXT_CHARS],
        },
    }


def _repository_metadata_value(key: str, value: str) -> str:
    if key == "Title":
        limit = MAX_REPOSITORY_TITLE_CHARS
    elif key == "Description of dataset":
        limit = MAX_REPOSITORY_LLM_DESCRIPTION_CHARS
    elif key == "Dataset URL":
        limit = MAX_REPOSITORY_LLM_URL_CHARS
    else:
        limit = MAX_REPOSITORY_LLM_METADATA_VALUE_CHARS
    return value[:limit]


def _parse_repository_relevance_classification(
    raw: dict[str, object],
) -> RepositoryClassification:
    if not isinstance(raw, dict):
        raise ClassificationError(
            "LLM classification output must be a JSON object.", code="llm_invalid_response"
        )

    label = _required_relevance_label(raw, "label")
    reason = _required_non_empty_string(raw, "reason")
    missing_information = _required_string_list(raw, "missing_information")
    try:
        return RepositoryClassification(
            relevance_label=label,
            reason=reason,
            missing_information=missing_information,
        )
    except ValueError as exception:
        raise ClassificationError(
            f"Invalid repository classification: {exception}", code="llm_invalid_response"
        ) from exception


def _required_relevance_label(
    raw: dict[str, object],
    field_name: str,
) -> RepositoryRelevanceLabel:
    value = raw.get(field_name)
    if not isinstance(value, str) or value not in REPOSITORY_RELEVANCE_LABELS:
        raise ClassificationError(
            f"LLM classification field {field_name} must be a supported relevance label.",
            code="llm_invalid_response",
        )
    return cast(RepositoryRelevanceLabel, value)


def _required_non_empty_string(raw: dict[str, object], field_name: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ClassificationError(
            f"LLM classification field {field_name} must be a non-empty string.",
            code="llm_invalid_response",
        )
    normalized_value = value.strip()
    if len(normalized_value) > MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS:
        raise ClassificationError(
            f"LLM classification field {field_name} is too long.", code="llm_invalid_response"
        )
    return normalized_value


def _required_string_list(raw: dict[str, object], field_name: str) -> list[str]:
    value = raw.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ClassificationError(
            f"LLM classification field {field_name} must be a list of strings.",
            code="llm_invalid_response",
        )
    normalized_items = [item.strip() for item in value if item.strip()]
    if len(normalized_items) > MAX_REPOSITORY_MISSING_INFORMATION_ITEMS:
        raise ClassificationError(
            f"LLM classification field {field_name} contains too many items.",
            code="llm_invalid_response",
        )
    if any(len(item) > MAX_REPOSITORY_MISSING_INFORMATION_CHARS for item in normalized_items):
        raise ClassificationError(
            f"LLM classification field {field_name} contains an item that is too long.",
            code="llm_invalid_response",
        )
    return normalized_items
