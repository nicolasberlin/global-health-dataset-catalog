"""Construct the classifiers used by default at pipeline entry points."""

from __future__ import annotations

import os

from collector.classification.checkpoints import CheckpointedLLMClient, VoteStore
from collector.classification.ensemble import (
    EnsemblePageClassifier,
    EnsembleRepositoryRelevanceClassifier,
)
from collector.classification.llm_client import HTTPJSONLLMClient
from collector.classification.page import PageClassifier
from collector.classification.page_llm_classifier import (
    LLMPageClassifier,
    _parse_page_classification,
)
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
    _parse_repository_relevance_classification,
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


def _voters(provider_builder, classifier_type, validate, vote_store):
    clients = [
        (
            voter_id,
            HTTPJSONLLMClient(
                provider=provider_builder(
                    name=voter_id,
                    model_env_var=model_env_var,
                    default_model=default_model,
                    api_key_env_var=api_key_env_var,
                ),
                model=os.getenv(model_env_var, default_model),
            ),
        )
        for voter_id, model_env_var, default_model, api_key_env_var in _DEFAULT_VOTERS
    ]
    configuration = (
        [{"voter_id": voter_id, **client.request_configuration()} for voter_id, client in clients]
        if vote_store is not None
        else []
    )
    return [
        (
            voter_id,
            classifier_type(
                client=(
                    CheckpointedLLMClient(client, vote_store, voter_id, configuration, validate)
                    if vote_store is not None
                    else client
                )
            ),
        )
        for voter_id, client in clients
    ]


def build_default_page_classifier(*, vote_store: VoteStore | None = None) -> PageClassifier:
    """Require three usable responses and two positives; optionally checkpoint each vote."""
    return EnsemblePageClassifier(
        _voters(
            epfl_rcp_chat_completions_provider_config,
            LLMPageClassifier,
            _parse_page_classification,
            vote_store,
        ),
        votes_required=2,
        minimum_successful_votes=3,
    )


def build_default_repository_result_classifier(
    *,
    vote_store: VoteStore | None = None,
) -> RepositoryResultClassifier:
    """Use the same durable voting policy with a separate repository relevance prompt."""
    return EnsembleRepositoryRelevanceClassifier(
        _voters(
            epfl_rcp_repository_relevance_provider_config,
            LLMRepositoryRelevanceClassifier,
            _parse_repository_relevance_classification,
            vote_store,
        ),
        votes_required=2,
        minimum_successful_votes=3,
    )
