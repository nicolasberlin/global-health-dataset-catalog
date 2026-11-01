"""Construct the default ensemble for relevance of external search candidates."""

from __future__ import annotations

from functools import partial

from collector.classification.relevance.classifier import (
    LLMRepositoryRelevanceClassifier,
    _parse_repository_relevance_classification,
)
from collector.classification.relevance.ensemble import EnsembleRepositoryRelevanceClassifier
from collector.classification.relevance.models import RepositoryResultClassifier
from collector.classification.relevance.prompts import (
    _build_epfl_rcp_repository_relevance_request_body,
)
from collector.llm.checkpoints import VoteStore
from collector.llm.providers.epfl_rcp import (
    epfl_rcp_chat_completions_provider_config,
)
from collector.llm.voter_factory import _voters


def build_default_repository_result_classifier(
    *,
    vote_store: VoteStore | None = None,
) -> RepositoryResultClassifier:
    """Use the same durable voting policy with a separate repository relevance prompt."""
    return EnsembleRepositoryRelevanceClassifier(
        _voters(
            partial(
                epfl_rcp_chat_completions_provider_config,
                request_body_builder=_build_epfl_rcp_repository_relevance_request_body,
            ),
            LLMRepositoryRelevanceClassifier,
            _parse_repository_relevance_classification,
            vote_store,
        ),
        votes_required=2,
        minimum_successful_votes=3,
    )
