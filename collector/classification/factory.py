from __future__ import annotations

from collector.classification.llm import (
    HTTPJSONLLMClient,
    LLMPageClassifier,
    openai_responses_provider_config,
)
from collector.classification.page import PageClassifier
from collector.config import DEFAULT_CONFIG, CollectorConfig


def build_default_page_classifier(
    config: CollectorConfig = DEFAULT_CONFIG,
) -> PageClassifier:
    return LLMPageClassifier(
        client=HTTPJSONLLMClient(provider=openai_responses_provider_config()),
        config=config,
    )
