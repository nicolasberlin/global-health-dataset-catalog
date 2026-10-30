from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

import pytest
from app.api.presenters.search import _collector_repository_candidate
from app.api.schemas.catalog import CollectorCollectedDataset
from app.api.schemas.search import CollectorRepositorySearchItem, CollectorRepositorySearchRequest
from app.auth.security import APIPrincipal
from app.db.catalog.search import normalize_dataset_search_query
from helpers.workflows import CANDIDATE_ID

from collector.classification.repository import RepositoryClassification

pytestmark = pytest.mark.anyio

SEARCH_ID = UUID("11111111-1111-4111-8111-111111111111")
PRINCIPAL = APIPrincipal(owner_id="test-user")


def _accepted_repository_ensemble(*, reason: str) -> dict[str, object]:
    voters = [
        {
            "voter_id": voter_id,
            "accepted": True,
            "relevance_label": "relevant",
            "reason": reason,
            "missing_information": [],
        }
        for voter_id in ("llm_a", "llm_b", "llm_c")
    ]
    return {
        "votes_required": 2,
        "minimum_successful_votes": 2,
        "successful_votes": 3,
        "failed_votes": 0,
        "accepted_votes": 3,
        "decision": "accepted",
        "decision_reason": "enough_accept_votes",
        "decision_voter_ids": ["llm_a", "llm_b", "llm_c"],
        "voters": voters,
        "failures": [],
    }


def _rejected_repository_ensemble(*, reason: str) -> dict[str, object]:
    voters = [
        {
            "voter_id": voter_id,
            "accepted": False,
            "relevance_label": "not_relevant",
            "reason": reason,
            "missing_information": [],
        }
        for voter_id in ("llm_a", "llm_b", "llm_c")
    ]
    return {
        "votes_required": 2,
        "minimum_successful_votes": 2,
        "successful_votes": 3,
        "failed_votes": 0,
        "accepted_votes": 0,
        "decision": "rejected",
        "decision_reason": "rejected_by_majority",
        "decision_voter_ids": ["llm_a", "llm_b", "llm_c"],
        "voters": voters,
        "failures": [],
    }


def _candidate(
    *,
    title: str = "Malaria mortality estimates",
    url: str = "https://example.org/datasets/malaria-mortality",
    status: str = "pending",
    classification: RepositoryClassification | None = None,
    error: str = "",
    search_query: str = "malaria mortality",
) -> dict[str, object]:
    return {
        "id": CANDIDATE_ID,
        "search_session_id": SEARCH_ID,
        "search_query": search_query,
        "title": title,
        "description": "Annual mortality estimates by country.",
        "url": url,
        "source": "DataCite",
        "publisher": "Global Health Repository",
        "publication_date": "2025",
        "doi": "10.1234/example",
        "keywords": ["malaria", "mortality"],
        "metadata": {"Title": title, "Geography": "France"},
        "classification_status": status,
        "classification": asdict(classification) if classification else None,
        "error": error,
        "created_at": "2026-09-06T12:00:00+00:00",
        "updated_at": "2026-09-06T12:00:00+00:00",
    }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("  malaria   mortality  ", "malaria mortality"),
        (
            "datasets about malaria mortality in France",
            "about malaria mortality in France",
        ),
        ("mortality datasets", "mortality"),
        ("DATA, dataset! databases", ""),
        ("database-driven surveillance", "database-driven surveillance"),
    ],
)
def test_normalize_dataset_search_query(query, expected):
    assert normalize_dataset_search_query(query) == expected


def test_collector_search_repositories_request_rejects_too_long_query():
    try:
        CollectorRepositorySearchRequest(query="x" * 301)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected validation error.")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("title", "x" * 501),
        ("description", "x" * 20_001),
        ("keywords", ["x" * 201]),
        ("metadata", {"blob": "x" * 100_001}),
    ],
)
def test_collector_repository_item_rejects_oversized_llm_input(
    field_name,
    value,
):
    item_data = {
        "candidate_id": CANDIDATE_ID,
        "search_id": SEARCH_ID,
        "title": "Malaria mortality estimates",
        "url": "https://example.org/datasets/malaria-mortality",
        "source": "DataCite",
        field_name: value,
    }

    with pytest.raises(ValueError):
        CollectorRepositorySearchItem(**item_data)


def test_collector_repository_item_rejects_incomplete_classification_contract():
    with pytest.raises(ValueError):
        CollectorRepositorySearchItem(
            candidate_id=CANDIDATE_ID,
            search_id=SEARCH_ID,
            title="Malaria mortality estimates",
            url="https://example.org/datasets/malaria-mortality",
            source="DataCite",
            classification={"accepted": True},
        )


def test_collected_dataset_response_rejects_non_http_dataset_url():
    with pytest.raises(ValueError):
        CollectorCollectedDataset(
            dataset_url="javascript:alert(1)",
            title="Invalid dataset",
            description="",
            publisher="",
            hosting_platform="",
            uploader="",
            discovery_method="html",
            dataset_signals={},
            distributions=[],
            validation_results=[],
        )


async def test_manual_source_collection_endpoint_is_removed():
    from app.main import app
    from starlette.routing import Match

    scope = {"type": "http", "method": "POST", "path": "/collector/collection-jobs"}
    assert all(route.matches(scope)[0] == Match.NONE for route in app.routes)
    assert "/collector/collection-jobs" not in app.openapi()["paths"]


def test_candidate_errors_are_public_messages_and_keep_internal_diagnostics():
    stored = _candidate(status="error", error="internal-only: private provider response")
    public = _collector_repository_candidate(stored)

    assert public.classification_error == "Candidate classification failed."
    assert public.classification_error_code == "classification_failed"
    assert "internal-only" not in public.model_dump_json()
    assert stored["error"] == "internal-only: private provider response"


def test_public_job_schema_does_not_advertise_private_candidate_id():
    from app.main import app

    properties = app.openapi()["components"]["schemas"]["CollectorCollectionJob"]["properties"]
    assert "repository_candidate_id" not in properties
    assert {"status", "saved_count", "source_url", "error_code"} <= properties.keys()
