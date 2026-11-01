"""Construct the default ensemble for dataset eligibility during collection."""

from __future__ import annotations

from functools import partial

from collector.collection.eligibility.classifier import (
    LLMPageClassifier,
    _parse_page_classification,
)
from collector.collection.eligibility.ensemble import EnsemblePageClassifier
from collector.collection.eligibility.models import PageClassifier
from collector.collection.eligibility.prompts import _build_dataset_page_eligibility_request_body
from collector.llm.checkpoints import VoteStore
from collector.llm.providers.epfl_rcp import (
    epfl_rcp_chat_completions_provider_config,
)
from collector.llm.voter_factory import build_llm_voters


def build_default_page_classifier(*, vote_store: VoteStore | None = None) -> PageClassifier:
    """Require three usable responses and two positives; optionally checkpoint each vote."""
    return EnsemblePageClassifier(
        build_llm_voters(
            partial(
                epfl_rcp_chat_completions_provider_config,
                request_body_builder=_build_dataset_page_eligibility_request_body,
            ),
            LLMPageClassifier,
            _parse_page_classification,
            vote_store,
        ),
        votes_required=2,
        minimum_successful_votes=3,
    )
