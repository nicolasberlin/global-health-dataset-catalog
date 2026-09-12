"""EPFL RCP Chat Completions configuration for classification prompts."""

from __future__ import annotations

from collector.classification.llm_client import (
    LLMProviderConfig,
    extract_chat_completions_message_text,
)
from collector.classification.prompts import (
    _build_epfl_rcp_chat_completions_request_body,
    _build_epfl_rcp_repository_relevance_request_body,
)

EPFL_RCP_CHAT_COMPLETIONS_URL = "https://inference-rcp.epfl.ch/v1/chat/completions"
DEFAULT_DEEPSEEK_RCP_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
DEFAULT_GEMMA_MEDITRON_MODEL = "EPFLiGHT/Gemma-3-27B-MeditronFO"
DEFAULT_APERTUS_MEDITRON_MODEL = "EPFLiGHT/Apertus-70B-MeditronFO"


def epfl_rcp_chat_completions_provider_config(
    *,
    name: str,
    model_env_var: str,
    default_model: str,
    api_key_env_var: str,
) -> LLMProviderConfig:
    """Build the EPFL RCP provider configuration for page eligibility."""
    return LLMProviderConfig(
        name=name,
        endpoint_url=EPFL_RCP_CHAT_COMPLETIONS_URL,
        api_key_env_var=api_key_env_var,
        model_env_var=model_env_var,
        default_model=default_model,
        request_body_builder=_build_epfl_rcp_chat_completions_request_body,
        response_text_extractor=extract_chat_completions_message_text,
    )


def epfl_rcp_repository_relevance_provider_config(
    *,
    name: str,
    model_env_var: str,
    default_model: str,
    api_key_env_var: str,
) -> LLMProviderConfig:
    """Build the EPFL RCP provider configuration for repository relevance."""
    return LLMProviderConfig(
        name=name,
        endpoint_url=EPFL_RCP_CHAT_COMPLETIONS_URL,
        api_key_env_var=api_key_env_var,
        model_env_var=model_env_var,
        default_model=default_model,
        request_body_builder=_build_epfl_rcp_repository_relevance_request_body,
        response_text_extractor=extract_chat_completions_message_text,
    )
