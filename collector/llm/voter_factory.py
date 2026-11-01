"""Shared default-voter configuration, client construction and readiness checks."""

from __future__ import annotations

import os
from dataclasses import dataclass

from collector.llm.checkpoints import CheckpointedLLMClient
from collector.llm.client import HTTPJSONLLMClient
from collector.llm.providers.epfl_rcp import (
    DEFAULT_APERTUS_MEDITRON_MODEL,
    DEFAULT_DEEPSEEK_RCP_MODEL,
    DEFAULT_GEMMA_MEDITRON_MODEL,
)


@dataclass(frozen=True)
class LLMVoterConfig:
    """Stable audit identity and explicit model and credential settings for one voter."""

    voter_id: str
    model_env_var: str
    default_model: str
    api_key_env_var: str


# Each voter has a stable audit ID, an independently configurable model, and
# an explicit credential source. No model has implicit configuration or key fallback.
_DEFAULT_VOTERS = (
    LLMVoterConfig(
        voter_id="epfl_rcp",
        model_env_var="RCP_DEEPSEEK_MODEL",
        default_model=DEFAULT_DEEPSEEK_RCP_MODEL,
        api_key_env_var="RCP_DEEPSEEK_API_KEY",
    ),
    LLMVoterConfig(
        voter_id="epfl_rcp_gemma_meditron",
        model_env_var="RCP_GEMMA_MEDITRON_MODEL",
        default_model=DEFAULT_GEMMA_MEDITRON_MODEL,
        api_key_env_var="RCP_GEMMA_MEDITRON_API_KEY",
    ),
    LLMVoterConfig(
        voter_id="epfl_rcp_apertus_meditron",
        model_env_var="RCP_APERTUS_MEDITRON_MODEL",
        default_model=DEFAULT_APERTUS_MEDITRON_MODEL,
        api_key_env_var="RCP_APERTUS_MEDITRON_API_KEY",
    ),
)


def validate_default_classifier_configuration() -> None:
    """Validate required local settings without creating clients or calling providers."""
    for config in _DEFAULT_VOTERS:
        if not os.getenv(config.api_key_env_var, "").strip() or not os.getenv(
            config.model_env_var, config.default_model,
        ).strip():
            raise ValueError("Required model configuration is missing or blank.")


def build_llm_voters(provider_builder, classifier_type, validate, vote_store):
    """Build the ordered model voters, optionally wrapping clients with durable checkpoints."""
    clients = [
        (
            config.voter_id,
            HTTPJSONLLMClient(
                provider=provider_builder(
                    name=config.voter_id,
                    model_env_var=config.model_env_var,
                    default_model=config.default_model,
                    api_key_env_var=config.api_key_env_var,
                ),
                model=os.getenv(config.model_env_var, config.default_model),
            ),
        )
        for config in _DEFAULT_VOTERS
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
