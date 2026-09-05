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
    epfl_rcp_chat_completions_provider_config,
    epfl_rcp_repository_relevance_provider_config,
)
from collector.classification.repository import RepositoryResultClassifier
from collector.classification.repository_llm_classifier import (
    LLMRepositoryRelevanceClassifier,
)


def build_default_page_classifier() -> PageClassifier:
    """Build the single-voter EPFL RCP page classifier used by collection.

    Both thresholds are one, so a missing key, provider failure, timeout, or
    unusable response fails classification instead of falling back or voting
    to reject.
    """
    return EnsemblePageClassifier(
        [
            (
                "epfl_rcp",
                LLMPageClassifier(
                    client=HTTPJSONLLMClient(
                        provider=epfl_rcp_chat_completions_provider_config(),
                    ),
                ),
            )
        ],
        votes_required=1,
        minimum_successful_votes=1,
    )


def build_default_repository_result_classifier() -> RepositoryResultClassifier:
    """Build the single-voter EPFL RCP classifier used by repository search.

    With one required successful vote, provider and response errors propagate
    as classification failures; only a valid relevance label can accept or
    reject the candidate.
    """
    return EnsembleRepositoryRelevanceClassifier(
        [
            (
                "epfl_rcp",
                LLMRepositoryRelevanceClassifier(
                    client=HTTPJSONLLMClient(
                        provider=epfl_rcp_repository_relevance_provider_config(),
                    ),
                ),
            )
        ],
        votes_required=1,
        minimum_successful_votes=1,
    )
