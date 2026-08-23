from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from collector.classification.page import PageClassification, PageClassificationError
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.storage.models import DistributionCandidate, HealthLabel, PageSnapshot

OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5"
MAX_PAGE_TEXT_CHARS = 4000
MAX_DISTRIBUTIONS = 10

HEALTH_LABELS: set[HealthLabel] = {"HEALTH", "PARTIALLY_HEALTH", "NON_HEALTH"}

RequestBodyBuilder = Callable[[dict[str, object], str], dict[str, object]]
ResponseTextExtractor = Callable[[object], str]


class LLMPageClassificationClient(Protocol):
    def classify_page(self, payload: dict[str, object]) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    endpoint_url: str
    api_key_env_var: str
    model_env_var: str
    default_model: str
    request_body_builder: RequestBodyBuilder
    response_text_extractor: ResponseTextExtractor
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "


class LLMPageClassifier:
    def __init__(
        self,
        client: LLMPageClassificationClient,
        config: CollectorConfig = DEFAULT_CONFIG,
    ) -> None:
        self._client = client
        self._config = config

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

        return _parse_page_classification(raw_classification, self._config)


class HTTPJSONLLMClient:
    def __init__(
        self,
        provider: LLMProviderConfig,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 20.0,
        request: Callable[..., object] = urlopen,
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._request = request

    def classify_page(self, payload: dict[str, object]) -> dict[str, object]:
        api_key = self._api_key or os.getenv(self._provider.api_key_env_var, "")
        if not api_key:
            raise PageClassificationError(
                f"{self._provider.api_key_env_var} is required for LLM page classification."
            )

        request = Request(
            self._provider.endpoint_url,
            data=json.dumps(self._request_body(payload)).encode("utf-8"),
            headers={
                self._provider.auth_header: f"{self._provider.auth_prefix}{api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._request(request, timeout=self._timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exception:
            raise PageClassificationError(
                f"{self._provider.name} classification request failed with HTTP {exception.code}."
            ) from exception
        except (TimeoutError, URLError) as exception:
            raise PageClassificationError(
                f"{self._provider.name} classification request failed."
            ) from exception
        except (json.JSONDecodeError, UnicodeDecodeError) as exception:
            raise PageClassificationError(
                f"{self._provider.name} classification response was not valid JSON."
            ) from exception

        output_text = self._provider.response_text_extractor(response_payload)

        try:
            raw_classification = json.loads(output_text)
        except json.JSONDecodeError as exception:
            raise PageClassificationError(
                f"{self._provider.name} classification output was not valid JSON."
            ) from exception

        if not isinstance(raw_classification, dict):
            raise PageClassificationError(
                f"{self._provider.name} classification output must be a JSON object."
            )

        return raw_classification

    def _request_body(self, payload: dict[str, object]) -> dict[str, object]:
        model = self._model or os.getenv(
            self._provider.model_env_var,
            self._provider.default_model,
        )
        return self._provider.request_body_builder(payload, model)


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
    config: CollectorConfig,
) -> PageClassification:
    if not isinstance(raw, dict):
        raise PageClassificationError("LLM classification output must be a JSON object.")

    dataset_probability = _required_probability(raw, "dataset_probability")
    health_probability = _required_probability(raw, "health_probability")
    health_label = _required_health_label(raw, "health_label")
    dataset_signals = _required_json_object(raw, "dataset_signals")
    health_signals = _required_json_object(raw, "health_signals")
    accepted = (
        dataset_probability >= config.min_dataset_probability
        and health_probability >= config.min_health_probability
        and health_label != "NON_HEALTH"

    )

    return PageClassification(
        accepted=accepted,
        dataset_probability=dataset_probability,
        health_probability=health_probability,
        health_label=health_label,
        dataset_signals=dataset_signals,
        health_signals=health_signals,
    )


def _required_probability(raw: dict[str, object], field_name: str) -> float:
    value = raw.get(field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PageClassificationError(
            f"LLM classification field {field_name} must be a number between 0 and 1."
        )

    probability = float(value)
    if not math.isfinite(probability) or probability < 0 or probability > 1:
        raise PageClassificationError(
            f"LLM classification field {field_name} must be a number between 0 and 1."
        )

    return probability


def _required_health_label(raw: dict[str, object], field_name: str) -> HealthLabel:
    value = raw.get(field_name)
    if value not in HEALTH_LABELS:
        raise PageClassificationError(
            f"LLM classification field {field_name} must be a supported health label."
        )
    return value


def _required_json_object(raw: dict[str, object], field_name: str) -> dict[str, object]:
    value = raw.get(field_name)
    if not isinstance(value, dict):
        raise PageClassificationError(f"LLM classification field {field_name} must be an object.")

    return _json_safe_object(value, field_name)


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


def _extract_openai_output_text(response_payload: object) -> str:
    if not isinstance(response_payload, dict):
        raise PageClassificationError("OpenAI response must be a JSON object.")

    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = response_payload.get("output")
    if isinstance(output, list):
        for output_item in output:
            if not isinstance(output_item, dict):
                continue

            content = output_item.get("content")
            if not isinstance(content, list):
                continue

            for content_item in content:
                if not isinstance(content_item, dict):
                    continue

                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    return text

    raise PageClassificationError("OpenAI response did not include classification text.")


def openai_responses_provider_config() -> LLMProviderConfig:
    return LLMProviderConfig(
        name="OpenAI",
        endpoint_url=OPENAI_RESPONSES_API_URL,
        api_key_env_var="OPENAI_API_KEY",
        model_env_var="OPENAI_MODEL",
        default_model=DEFAULT_OPENAI_MODEL,
        request_body_builder=_build_openai_responses_request_body,
        response_text_extractor=_extract_openai_output_text,
    )


def _build_openai_responses_request_body(
    payload: dict[str, object],
    model: str,
) -> dict[str, object]:
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": _system_prompt(),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(payload, ensure_ascii=True),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "global_health_page_classification",
                "strict": True,
                "schema": _classification_schema(),
            }
        },
    }


def _system_prompt() -> str:
    return (
        "Classify whether this page describes an individual global health dataset. "
        "Return calibrated probabilities from 0 to 1 for dataset relevance and health "
        "relevance. The backend derives the final accepted decision from configured "
        "thresholds, so do not encode the final decision in the response. Dataset-relevant "
        "pages describe an individual dataset, downloadable data resource, or API-backed "
        "dataset. Health-relevant pages concern health, clinical, epidemiology, public "
        "health, healthcare, disease, mortality, morbidity, vaccination, or similar topics. "
        "Keep signals concise and JSON-safe."
    )


def _classification_schema() -> dict[str, object]:
    signal_schema = {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "evidence": {"type": "string"},
        },
        "required": ["reason", "evidence"],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "dataset_probability": {"type": "number"},
            "health_probability": {"type": "number"},
            "health_label": {
                "type": "string",
                "enum": ["HEALTH", "PARTIALLY_HEALTH", "NON_HEALTH"],
            },
            "dataset_signals": signal_schema,
            "health_signals": signal_schema,
        },
        "required": [
            "dataset_probability",
            "health_probability",
            "health_label",
            "dataset_signals",
            "health_signals",
        ],
        "additionalProperties": False,
    }
