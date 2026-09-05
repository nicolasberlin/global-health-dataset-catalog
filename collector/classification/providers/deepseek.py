"""DeepSeek Responses API configuration for classification prompts."""

from __future__ import annotations

from collector.classification.llm_client import (
    LLMProviderConfig,
    extract_responses_output_text,
)
from collector.classification.prompts import (
    _build_deepseek_repository_relevance_request_body,
    _build_deepseek_responses_request_body,
)

DEEPSEEK_RESPONSES_API_URL = "https://api.deepseek.com/responses"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


def deepseek_responses_provider_config(
    name: str = "DeepSeek",
    model_env_var: str = "DEEPSEEK_CLASSIFIER_MODEL",
    default_model: str = DEFAULT_DEEPSEEK_MODEL,
) -> LLMProviderConfig:
    """Build the DeepSeek provider configuration for page eligibility."""
    return LLMProviderConfig(
        name=name,
        endpoint_url=DEEPSEEK_RESPONSES_API_URL,
        api_key_env_var="DEEPSEEK_API_KEY",
        model_env_var=model_env_var,
        default_model=default_model,
        request_body_builder=_build_deepseek_responses_request_body,
        response_text_extractor=extract_responses_output_text,
    )


def deepseek_repository_relevance_provider_config(
    name: str = "DeepSeek",
    model_env_var: str = "DEEPSEEK_CLASSIFIER_MODEL",
    default_model: str = DEFAULT_DEEPSEEK_MODEL,
) -> LLMProviderConfig:
    """Build the DeepSeek provider configuration for repository relevance."""
    return LLMProviderConfig(
        name=name,
        endpoint_url=DEEPSEEK_RESPONSES_API_URL,
        api_key_env_var="DEEPSEEK_API_KEY",
        model_env_var=model_env_var,
        default_model=default_model,
        request_body_builder=_build_deepseek_repository_relevance_request_body,
        response_text_extractor=extract_responses_output_text,
    )
