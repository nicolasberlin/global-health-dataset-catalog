from __future__ import annotations

import os

from collector.classification.ensemble import EnsemblePageClassifier
from collector.classification.llm import (
    HTTPJSONLLMClient,
    LLMPageClassifier,
    openai_responses_provider_config,
)
from collector.classification.page import PageClassificationError, PageClassifier
from collector.config import DEFAULT_CONFIG, CollectorConfig

OPENAI_CLASSIFIER_VOTERS: tuple[tuple[str, str], ...] = (
    ("openai_primary", "OPENAI_CLASSIFIER_MODEL_1"),
    ("openai_secondary", "OPENAI_CLASSIFIER_MODEL_2"),
    ("openai_tertiary", "OPENAI_CLASSIFIER_MODEL_3"),
)


def build_default_page_classifier(
    config: CollectorConfig = DEFAULT_CONFIG,
) -> PageClassifier:
    return EnsemblePageClassifier(
        [
            (
                voter_id,
                LLMPageClassifier(
                    client=HTTPJSONLLMClient(
                        provider=openai_responses_provider_config(
                            name=f"OpenAI {voter_id}",
                            model_env_var=model_env_var,
                            default_model=model,
                        ),
                        model=model,
                    ),
                    config=config,
                ),
            )
            for voter_id, model_env_var, model in _openai_classifier_models()
        ],
        votes_required=2,
        minimum_successful_votes=2,
    )


def _openai_classifier_models() -> tuple[tuple[str, str, str], ...]:
    models = tuple(
        (
            voter_id,
            model_env_var,
            os.getenv(model_env_var, "").strip(),
        )
        for voter_id, model_env_var in OPENAI_CLASSIFIER_VOTERS
    )
    missing_env_vars = [
        model_env_var
        for _voter_id, model_env_var, model in models
        if not model
    ]
    if missing_env_vars:
        raise PageClassificationError(
            "Three distinct OpenAI classifier models must be configured: "
            f"{', '.join(missing_env_vars)}."
        )

    model_names = [model for _voter_id, _model_env_var, model in models]
    if len(set(model_names)) != len(model_names):
        raise PageClassificationError(
            "OpenAI classifier models must be distinct across "
            "OPENAI_CLASSIFIER_MODEL_1, OPENAI_CLASSIFIER_MODEL_2, "
            "and OPENAI_CLASSIFIER_MODEL_3."
        )

    return models
