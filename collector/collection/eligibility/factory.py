"""Construct the default ensemble for dataset eligibility during collection."""

from __future__ import annotations

from collector.classification.checkpoints import VoteStore
from collector.classification.providers.epfl_rcp import (
    epfl_rcp_chat_completions_provider_config,
)
from collector.classification.voter_factory import _voters
from collector.collection.eligibility.ensemble import EnsemblePageClassifier
from collector.collection.eligibility.llm import LLMPageClassifier, _parse_page_classification
from collector.collection.eligibility.models import PageClassifier


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
