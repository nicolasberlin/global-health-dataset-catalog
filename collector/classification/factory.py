"""Construct the classifiers used by default at pipeline entry points."""

from __future__ import annotations

from collector.classification.ensemble import (
    EnsemblePageClassifier,
    EnsembleRepositoryRelevanceClassifier,
)
from collector.classification.llm_client import HTTPJSONLLMClient
from collector.classification.page import PageClassifier
from collector.classification.page_llm_classifier import LLMPageClassifier
from collector.classification.providers.epfl_rcp import (
    DEFAULT_APERTUS_MEDITRON_MODEL,
    DEFAULT_DEEPSEEK_RCP_MODEL,
    DEFAULT_GEMMA_MEDITRON_MODEL,
    epfl_rcp_chat_completions_provider_config,
    epfl_rcp_repository_relevance_provider_config,
)
from collector.classification.repository import RepositoryResultClassifier
from collector.classification.repository_llm_classifier import (
    LLMRepositoryRelevanceClassifier,
)

# Each voter has a stable audit ID, an independently configurable model, and
# an explicit credential source. No model has implicit configuration or key fallback.
_DEFAULT_VOTERS = (
    ("epfl_rcp", "RCP_DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_RCP_MODEL, "RCP_DEEPSEEK_API_KEY"),
    (
        "epfl_rcp_gemma_meditron",
        "RCP_GEMMA_MEDITRON_MODEL",
        DEFAULT_GEMMA_MEDITRON_MODEL,
        "RCP_GEMMA_MEDITRON_API_KEY",
    ),
    (
        "epfl_rcp_apertus_meditron",
        "RCP_APERTUS_MEDITRON_MODEL",
        DEFAULT_APERTUS_MEDITRON_MODEL,
        "RCP_APERTUS_MEDITRON_API_KEY",
    ),
)


def build_default_page_classifier() -> PageClassifier:
    """Build three parallel voters with a two-out-of-three acceptance threshold.

    Require all three responses to be usable: credential, transport or parsing
    failures must remain classification errors rather than semantic rejections.
    """
    return EnsemblePageClassifier(
        [
            (
                voter_id,
                LLMPageClassifier(
                    client=HTTPJSONLLMClient(
                        provider=epfl_rcp_chat_completions_provider_config(
                            name=voter_id,
                            model_env_var=model_env_var,
                            default_model=default_model,
                            api_key_env_var=api_key_env_var,
                        ),
                    ),
                ),
            )
            for voter_id, model_env_var, default_model, api_key_env_var in _DEFAULT_VOTERS
        ],
        votes_required=2,
        minimum_successful_votes=3,
    )


def build_default_repository_result_classifier() -> RepositoryResultClassifier:
    """Build the same three-model ensemble for repository query relevance.

    Two positive votes are required, and all three models must return usable
    responses. The page and repository prompts remain separate.
    """
    return EnsembleRepositoryRelevanceClassifier(
        [
            (
                voter_id,
                LLMRepositoryRelevanceClassifier(
                    client=HTTPJSONLLMClient(
                        provider=epfl_rcp_repository_relevance_provider_config(
                            name=voter_id,
                            model_env_var=model_env_var,
                            default_model=default_model,
                            api_key_env_var=api_key_env_var,
                        ),
                    ),
                ),
            )
            for voter_id, model_env_var, default_model, api_key_env_var in _DEFAULT_VOTERS
        ],
        votes_required=2,
        minimum_successful_votes=3,
    )
