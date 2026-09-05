"""OpenAI Responses API configuration for classification prompts."""

from __future__ import annotations

from collector.classification.llm_client import (
    LLMProviderConfig,
    extract_responses_output_text,
)
from collector.classification.prompts import (
    _build_openai_repository_relevance_request_body,
    _build_openai_responses_request_body,
)

OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5"


def openai_responses_provider_config(
    name: str = "OpenAI",
    model_env_var: str = "OPENAI_MODEL",
    default_model: str = DEFAULT_OPENAI_MODEL,
) -> LLMProviderConfig:
    """Build the OpenAI provider configuration for page eligibility."""

    return LLMProviderConfig(
        name=name,
        endpoint_url=OPENAI_RESPONSES_API_URL,
        api_key_env_var="OPENAI_API_KEY",
        model_env_var=model_env_var,
        default_model=default_model,
        request_body_builder=_build_openai_responses_request_body,
        response_text_extractor=extract_responses_output_text,
    )


def openai_repository_relevance_provider_config(
    name: str = "OpenAI",
    model_env_var: str = "OPENAI_MODEL",
    default_model: str = DEFAULT_OPENAI_MODEL,
) -> LLMProviderConfig:
    """Build the OpenAI provider configuration for repository relevance."""

    return LLMProviderConfig(
        name=name,
        endpoint_url=OPENAI_RESPONSES_API_URL,
        api_key_env_var="OPENAI_API_KEY",
        model_env_var=model_env_var,
        default_model=default_model,
        request_body_builder=_build_openai_repository_relevance_request_body,
        response_text_extractor=extract_responses_output_text,
    )
