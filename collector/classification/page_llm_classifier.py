from __future__ import annotations

import math

from collector.classification.llm_client import LLMPageClassificationClient
from collector.classification.page import PageClassification, PageClassificationError
from collector.storage.models import DistributionCandidate, PageSnapshot

MAX_PAGE_TEXT_CHARS = 4000
MAX_DISTRIBUTIONS = 10


class LLMPageClassifier:
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
    return {
        "page": {
            "url": page.url,
            "canonical_url": page.canonical_url,
            "title": page.title,
            "h1": page.h1,
            "meta_description": page.meta_description,
            "og_title": page.og_title,
            "og_description": page.og_description,
            "headings": list(page.headings[:20]),
            "publisher": page.publisher,
            "hosting_platform": page.hosting_platform,
            "uploader": page.uploader,
            "metadata": page.dataset_metadata(),
            "text": page.text[:MAX_PAGE_TEXT_CHARS],
        },
        "distributions": [
            {
                "url": distribution.url,
                "format": distribution.format,
                "probability": distribution.probability,
                "anchor": distribution.anchor,
                "mime_type": distribution.mime_type,
                "nearby_text": distribution.nearby_text,
            }
            for distribution in distributions[:MAX_DISTRIBUTIONS]
        ],
    }


def _parse_page_classification(
    raw: dict[str, object],
) -> PageClassification:
    if not isinstance(raw, dict):
        raise PageClassificationError("LLM classification output must be a JSON object.")

    accepted = _required_bool(raw, "accepted")
    dataset_signals = _required_signal_object(raw, "dataset_signals")
    health_signals = _required_signal_object(raw, "health_signals")

    return PageClassification(
        accepted=accepted,
        dataset_signals=dataset_signals,
        health_signals=health_signals,
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
