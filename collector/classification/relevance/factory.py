"""Construct the default ensemble for relevance of external search candidates."""

from __future__ import annotations

from collector.classification.checkpoints import VoteStore
from collector.classification.providers.epfl_rcp import (
    epfl_rcp_repository_relevance_provider_config,
)
from collector.classification.relevance.ensemble import EnsembleRepositoryRelevanceClassifier
from collector.classification.relevance.llm import (
    LLMRepositoryRelevanceClassifier,
    _parse_repository_relevance_classification,
)
from collector.classification.relevance.models import RepositoryResultClassifier
from collector.classification.voter_factory import _voters


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
