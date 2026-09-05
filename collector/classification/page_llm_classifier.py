"""LLM-backed classification of discovered dataset pages."""

from __future__ import annotations

import math

from collector.classification.llm_client import LLMPageClassificationClient
from collector.classification.page import PageClassification, PageClassificationError
from collector.storage.models import DistributionCandidate, PageSnapshot

# Bound untrusted evidence so model requests have predictable size.
MAX_PAGE_TEXT_CHARS = 4_000
MAX_PAGE_URL_CHARS = 2_048
MAX_PAGE_SHORT_TEXT_CHARS = 500
MAX_PAGE_DESCRIPTION_CHARS = 6_000
MAX_PAGE_METADATA_VALUE_CHARS = 1_500
MAX_PAGE_DISTRIBUTION_CONTEXT_CHARS = 1_000
MAX_PAGE_FORMAT_CHARS = 100
MAX_HEADINGS = 20
MAX_DISTRIBUTIONS = 10


class LLMPageClassifier:
    """Ask an LLM whether a discovered page is eligible for collection.

    The payload independently bounds page text, metadata, headings, and the
    first ``MAX_DISTRIBUTIONS`` candidates. Provider errors and malformed
    decisions raise ``PageClassificationError``; a valid ``accepted=false``
    response is a normal rejection.
    """

    def __init__(
        self,
        client: LLMPageClassificationClient,
    ) -> None:
        self._client = client

    def classify(
        self,
        page: PageSnapshot,
        distributions: list[DistributionCandidate],
    ) -> PageClassification:
        payload = _build_llm_payload(page, distributions)

        try:
            raw_classification = self._client.classify_page(payload)
        except PageClassificationError:
            raise
        except Exception as exception:
            raise PageClassificationError("LLM page classification failed.") from exception

        return _parse_page_classification(raw_classification)


def _build_llm_payload(
    page: PageSnapshot,
    distributions: list[DistributionCandidate],
) -> dict[str, object]:
    metadata = {
        key: _bounded_metadata_value(key, value)
        for key, value in page.dataset_metadata().items()
    }

    return {
        "page": {
            "url": page.url[:MAX_PAGE_URL_CHARS],
            "canonical_url": page.canonical_url[:MAX_PAGE_URL_CHARS],
            "title": page.title[:MAX_PAGE_SHORT_TEXT_CHARS],
            "h1": page.h1[:MAX_PAGE_SHORT_TEXT_CHARS],
            "meta_description": page.meta_description[:MAX_PAGE_DESCRIPTION_CHARS],
            "og_title": page.og_title[:MAX_PAGE_SHORT_TEXT_CHARS],
            "og_description": page.og_description[:MAX_PAGE_DESCRIPTION_CHARS],
            "headings": [
                heading[:MAX_PAGE_SHORT_TEXT_CHARS]
                for heading in page.headings[:MAX_HEADINGS]
            ],
            "publisher": page.publisher[:MAX_PAGE_SHORT_TEXT_CHARS],
            "hosting_platform": page.hosting_platform[:MAX_PAGE_SHORT_TEXT_CHARS],
            "uploader": page.uploader[:MAX_PAGE_SHORT_TEXT_CHARS],
            "metadata": metadata,
            "text": page.text[:MAX_PAGE_TEXT_CHARS],
        },
        "distributions": [
            {
                "url": distribution.url[:MAX_PAGE_URL_CHARS],
                "format": distribution.format[:MAX_PAGE_FORMAT_CHARS],
                "probability": distribution.probability,
                "anchor": distribution.anchor[:MAX_PAGE_DISTRIBUTION_CONTEXT_CHARS],
                "mime_type": distribution.mime_type[:MAX_PAGE_FORMAT_CHARS],
                "nearby_text": distribution.nearby_text[
                    :MAX_PAGE_DISTRIBUTION_CONTEXT_CHARS
                ],
            }
            for distribution in distributions[:MAX_DISTRIBUTIONS]
        ],
    }


def _bounded_metadata_value(key: str, value: str) -> str:
    if key == "Description of dataset":
        limit = MAX_PAGE_DESCRIPTION_CHARS
    elif key == "Dataset URL":
        limit = MAX_PAGE_URL_CHARS
    elif key == "Title":
        limit = MAX_PAGE_SHORT_TEXT_CHARS
    else:
        limit = MAX_PAGE_METADATA_VALUE_CHARS

    return value[:limit]


def _parse_page_classification(
    raw: dict[str, object],
) -> PageClassification:
    if not isinstance(raw, dict):
        raise PageClassificationError("LLM classification output must be a JSON object.")

    accepted = _required_bool(raw, "accepted")
    dataset_signals = _required_signal_object(raw, "dataset_signals")

    return PageClassification(
        accepted=accepted,
        dataset_signals=dataset_signals,
    )


def _required_bool(raw: dict[str, object], field_name: str) -> bool:
    value = raw.get(field_name)
    if not isinstance(value, bool):
        raise PageClassificationError(
            f"LLM classification field {field_name} must be a boolean."
        )
    return value


def _required_json_object(raw: dict[str, object], field_name: str) -> dict[str, object]:
    value = raw.get(field_name)
    if not isinstance(value, dict):
        raise PageClassificationError(f"LLM classification field {field_name} must be an object.")

    return _json_safe_object(value, field_name)


def _required_signal_object(
    raw: dict[str, object],
    field_name: str,
) -> dict[str, object]:
    value = _required_json_object(raw, field_name)
    expected_fields = {"reason", "evidence"}
    if set(value) != expected_fields:
        raise PageClassificationError(
            f"LLM classification field {field_name} must contain exactly "
            "reason and evidence."
        )
    for signal_field in expected_fields:
        if not isinstance(value[signal_field], str):
            raise PageClassificationError(
                f"LLM classification field {field_name}.{signal_field} "
                "must be a string."
            )
    return value


def _json_safe_object(value: dict[object, object], field_name: str) -> dict[str, object]:
    try:
        safe_value = _json_safe_value(value)
    except (TypeError, ValueError) as exception:
        raise PageClassificationError(
            f"LLM classification field {field_name} must be JSON-safe."
        ) from exception

    if not isinstance(safe_value, dict):
        raise PageClassificationError(f"LLM classification field {field_name} must be an object.")

    return safe_value


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value

    if isinstance(value, (int, float)):
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError("Invalid JSON number.")
        return value

    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]

    if isinstance(value, dict):
        safe_dict: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings.")
            safe_dict[key] = _json_safe_value(item)
        return safe_dict

    raise TypeError("Unsupported JSON value.")
