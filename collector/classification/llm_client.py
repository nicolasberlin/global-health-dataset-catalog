"""Provider-neutral HTTP client contracts for LLM classification."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collector.budget import check_collection_budget, read_with_budget, remaining_timeout
from collector.classification.page import PageClassificationError
from collector.diagnostics import retry_after
from collector.observability import measure_operation

RequestBodyBuilder = Callable[[dict[str, object], str], dict[str, object]]
ResponseTextExtractor = Callable[[object], str]
MAX_LLM_RESPONSE_BYTES = 2 * 1024 * 1024


class _RejectLLMRedirects(HTTPRedirectHandler):
    """Require a direct provider endpoint; never forward credentials on redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def extract_chat_completions_message_text(response_payload: object) -> str:
    """Extract assistant text from an OpenAI-compatible Chat Completions envelope."""
    if not isinstance(response_payload, dict):
        raise PageClassificationError(
            "LLM response must be a JSON object.", code="llm_invalid_response"
        )

    choices = response_payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content

    raise PageClassificationError(
        "LLM response did not include classification text.", code="llm_invalid_response"
    )


class LLMPageClassificationClient(Protocol):
    """Client capable of returning one structured page-classification decision."""

    def classify_page(self, payload: dict[str, object]) -> dict[str, object]: ...


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
        request: Callable[..., object] | None = None,
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._request = request if request is not None else build_opener(_RejectLLMRedirects()).open

    def classify_page(self, payload: dict[str, object]) -> dict[str, object]:
        return self.classify_request(self.prepare_request(payload))

    def prepare_request(self, payload: dict[str, object]) -> dict[str, object]:
        """Capture the complete provider body, excluding authentication secrets."""
        return self._request_body(payload)

    def request_configuration(self) -> dict[str, object]:
        return {"endpoint": self._provider.endpoint_url, "body": self.prepare_request({})}

    def classify_request(self, request_body: dict[str, object]) -> dict[str, object]:
        """Perform one synchronous provider request and require JSON output.

        Missing configuration, HTTP and timeout failures, malformed provider
        envelopes, and non-object model output all become
        ``PageClassificationError``.
        """

        with measure_operation("provider_request") as measurement:
            return self._classify_request(request_body, measurement)

    def _classify_request(self, request_body, measurement):
        check_collection_budget()
        api_key = self._api_key or os.getenv(self._provider.api_key_env_var, "")
        if not api_key:
            measurement["outcome"] = "configuration_error"
            raise PageClassificationError(
                f"{self._provider.api_key_env_var} is required for LLM page classification.",
                code="llm_configuration_error",
                recovery="configuration_required",
            )

        headers = {
            "Content-Type": "application/json",
            **self._provider.extra_headers,
            self._provider.auth_header: f"{self._provider.auth_prefix}{api_key}",
        }
        request = Request(
            self._provider.endpoint_url,
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        measurement["outcome"] = "failed"
        try:
            with self._request(
                request, timeout=remaining_timeout(self._timeout_seconds),
            ) as response:
                payload_bytes = read_with_budget(response, MAX_LLM_RESPONSE_BYTES + 1)
                measurement["outcome"] = "invalid_response"
                if len(payload_bytes) > MAX_LLM_RESPONSE_BYTES:
                    raise PageClassificationError(
                        "Provider response is too large.",
                        code="llm_response_too_large",
                        recovery="none",
                    )
                response_payload = json.loads(payload_bytes.decode("utf-8"))
        except HTTPError as exception:
            with exception if exception.fp is not None else nullcontext():
                check_collection_budget()
                measurement["outcome"] = "http_error"
                code = {
                    400: "llm_configuration_error", 401: "llm_configuration_error",
                    403: "llm_configuration_error", 404: "llm_configuration_error",
                    422: "llm_configuration_error", 429: "llm_rate_limited",
                    500: "llm_unavailable", 502: "llm_unavailable",
                    503: "llm_unavailable", 504: "llm_unavailable",
                }.get(exception.code, "processing_failed")
                if 300 <= exception.code < 400:
                    code = "llm_configuration_error"
                raise PageClassificationError(
                    f"{self._provider.name} classification request failed "
                    f"with HTTP {exception.code}.",
                    code=code,
                    recovery="configuration_required"
                    if code == "llm_configuration_error"
                    else "manual",
                    retry_at=retry_after(
                        exception.headers.get("Retry-After") if exception.headers else None
                    ),
                ) from exception
        except (TimeoutError, URLError, OSError) as exception:
            check_collection_budget()
            measurement["outcome"] = (
                "timeout"
                if isinstance(exception, TimeoutError)
                or isinstance(getattr(exception, "reason", None), TimeoutError)
                else "network_error"
            )
            raise PageClassificationError(
                f"{self._provider.name} classification request failed.",
                code="llm_timeout" if measurement["outcome"] == "timeout" else "llm_network_error",
            ) from exception
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exception:
            raise PageClassificationError(
                f"{self._provider.name} classification response was not valid JSON.",
                code="llm_invalid_response",
            ) from exception

        output_text = self._provider.response_text_extractor(response_payload)

        # The provider envelope is JSON, while output_text contains the model's
        # separate JSON classification document.
        try:
            raw_classification = json.loads(output_text)
        except (json.JSONDecodeError, RecursionError) as exception:
            raise PageClassificationError(
                f"{self._provider.name} classification output was not valid JSON.",
                code="llm_invalid_response",
            ) from exception

        if not isinstance(raw_classification, dict):
            raise PageClassificationError(
                f"{self._provider.name} classification output must be a JSON object.",
                code="llm_invalid_response",
            )

        measurement["outcome"] = "success"
        return raw_classification

    def _request_body(self, payload: dict[str, object]) -> dict[str, object]:
        model = self._model or os.getenv(
            self._provider.model_env_var,
            self._provider.default_model,
        )
        return self._provider.request_body_builder(payload, model)
