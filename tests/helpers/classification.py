"""Synthetic classifier responses and page builders; never calls live providers."""

from __future__ import annotations

import io
import json

from collector.storage.models import DistributionCandidate, PageSnapshot

MODELS = (
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "EPFLiGHT/Gemma-3-27B-MeditronFO",
    "EPFLiGHT/Apertus-70B-MeditronFO",
)


MODEL_VARIABLES = ("RCP_DEEPSEEK_MODEL", "RCP_GEMMA_MEDITRON_MODEL", "RCP_APERTUS_MEDITRON_MODEL")


KEY_VARIABLES = (
    "RCP_DEEPSEEK_API_KEY",
    "RCP_GEMMA_MEDITRON_API_KEY",
    "RCP_APERTUS_MEDITRON_API_KEY",
)


KEYS = ("test-deepseek-key", "test-gemma-key", "test-apertus-key")


PAGE = PageSnapshot(
    url="https://example.org/dataset",
    canonical_url="https://example.org/dataset",
    title="Infant mortality by country",
    search_query="infant mortality",
)


def response(kind, accepted):
    decision = (
        {"accepted": accepted, "dataset_signals": {"reason": "Test vote", "evidence": "Title"}}
        if kind == "page"
        else {
            "label": "relevant" if accepted else "not_relevant",
            "reason": "Test vote",
            "missing_information": [],
        }
    )
    return io.BytesIO(
        json.dumps({"choices": [{"message": {"content": json.dumps(decision)}}]}).encode()
    )


def page() -> PageSnapshot:
    return PageSnapshot(
        url="https://example.org/datasets/mortality",
        canonical_url="https://example.org/datasets/mortality",
        title="Mortality health dataset",
        h1="Mortality health dataset",
        meta_description="Official mortality and epidemiology data.",
        publisher="National Health Agency",
        text="Download CSV data for mortality indicators.",
        geography=("France",),
        date_of_publication="2025",
        dataset_url="https://example.org/datasets/mortality",
        diseases=("malaria",),
        size_of_dataset="12,000 records",
        demographic_information=("age", "sex"),
        sharing_license="CC-BY-4.0",
        modality_of_data=("tabular",),
        description_of_dataset="Official mortality and epidemiology data.",
    )


def distribution() -> DistributionCandidate:
    return DistributionCandidate(
        url="https://example.org/files/mortality.csv",
        format="CSV",
        probability=0.95,
        anchor="Download CSV",
        mime_type="text/csv",
    )
