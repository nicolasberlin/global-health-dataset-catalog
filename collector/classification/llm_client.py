"""Provider-neutral HTTP client contracts for LLM classification."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from collector.classification.page import PageClassificationError

RequestBodyBuilder = Callable[[dict[str, object], str], dict[str, object]]
ResponseTextExtractor = Callable[[object], str]


class LLMPageClassificationClient(Protocol):
    """Client capable of returning one structured page-classification decision."""

    def classify_page(self, payload: dict[str, object]) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class LLMProviderConfig:
    """HTTP and payload conventions required by one LLM provider."""

    name: str
    endpoint_url: str
    api_key_env_var: str
    model_env_var: str
    default_model: str
    request_body_builder: RequestBodyBuilder
    response_text_extractor: ResponseTextExtractor
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    extra_headers: Mapping[str, str] = field(default_factory=dict)


class HTTPJSONLLMClient:
    """Call an LLM HTTP endpoint and return its JSON classification object."""

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

        headers = {
            "Content-Type": "application/json",
            **self._provider.extra_headers,
            self._provider.auth_header: f"{self._provider.auth_prefix}{api_key}",
        }
        request = Request(
            self._provider.endpoint_url,
            data=json.dumps(self._request_body(payload)).encode("utf-8"),
            headers=headers,
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

        # The provider envelope is JSON, while output_text contains the model's
        # separate JSON classification document.
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
