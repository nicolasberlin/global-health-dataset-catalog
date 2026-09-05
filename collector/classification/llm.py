"""Compatibility exports for the split LLM classification modules."""

from collector.classification.llm_client import (
    HTTPJSONLLMClient,
    LLMPageClassificationClient,
    LLMProviderConfig,
    RequestBodyBuilder,
    ResponseTextExtractor,
    extract_chat_completions_message_text,
)
from collector.classification.page_llm_classifier import LLMPageClassifier
from collector.classification.providers.deepseek import (
    DEEPSEEK_RESPONSES_API_URL,
    DEFAULT_DEEPSEEK_MODEL,
    deepseek_repository_relevance_provider_config,
    deepseek_responses_provider_config,
)
from collector.classification.providers.epfl_rcp import (
    DEFAULT_EPFL_RCP_MODEL,
    EPFL_RCP_CHAT_COMPLETIONS_URL,
    epfl_rcp_chat_completions_provider_config,
    epfl_rcp_repository_relevance_provider_config,
)
from collector.classification.providers.openai import (
    DEFAULT_OPENAI_MODEL,
    OPENAI_RESPONSES_API_URL,
    openai_repository_relevance_provider_config,
    openai_responses_provider_config,
)
from collector.classification.repository_llm_classifier import (
    LLMRepositoryRelevanceClassifier,
)

__all__ = [
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_EPFL_RCP_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "DEEPSEEK_RESPONSES_API_URL",
    "EPFL_RCP_CHAT_COMPLETIONS_URL",
    "HTTPJSONLLMClient",
    "LLMPageClassificationClient",
    "LLMPageClassifier",
    "LLMProviderConfig",
    "LLMRepositoryRelevanceClassifier",
    "OPENAI_RESPONSES_API_URL",
    "RequestBodyBuilder",
    "ResponseTextExtractor",
    "deepseek_repository_relevance_provider_config",
    "deepseek_responses_provider_config",
    "epfl_rcp_chat_completions_provider_config",
    "epfl_rcp_repository_relevance_provider_config",
    "extract_chat_completions_message_text",
    "openai_repository_relevance_provider_config",
    "openai_responses_provider_config",
]
