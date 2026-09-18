from __future__ import annotations

import asyncio
import threading
import time
from copy import deepcopy
from dataclasses import asdict, replace
from uuid import UUID

import pytest
from app.database import (
    CandidateClassificationCompletion,
    CollectionJobReservation,
    normalize_dataset_search_query,
)
from app.routes import collector as collector_routes
from app.routes.collector import (
    _collector_repository_candidate,
    classify_repository_result,
    list_collected,
    read_collection_job,
    search_datasets,
)
from app.routes.collector_schemas import (
    CollectorCollectedDataset,
    CollectorRepositoryCandidateClassificationRequest,
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
)
from app.security import APIPrincipal
from fastapi import HTTPException

from collector.classification.page import PageClassificationError
from collector.classification.repository import RepositoryClassification
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchResult,
)
from collector.storage.models import (
    CollectedDataset,
    DistributionCandidate,
    ValidationResult,
)

pytestmark = pytest.mark.anyio

SEARCH_ID = UUID("11111111-1111-4111-8111-111111111111")
CANDIDATE_ID = UUID("22222222-2222-4222-8222-222222222222")
PRINCIPAL = APIPrincipal(owner_id="test-user")


@pytest.fixture(autouse=True)
def bypass_api_quota(monkeypatch):
    async def allow_request(principal, operation):
        assert principal == PRINCIPAL
        assert operation in {
            "repository_search",
            "repository_classification",
        }

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", allow_request)
    _use_pending_collection(monkeypatch)


def _use_accepting_repository_classifier(monkeypatch):
    class AcceptingRepositoryClassifier:
        def classify(self, page):
            return RepositoryClassification(
                relevance_label="relevant",
                reason=f"{page.title} matches the search query.",
                ensemble=_accepted_repository_ensemble(
                    reason=f"{page.title} matches the search query."
                ),
            )

    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda: AcceptingRepositoryClassifier(),
    )


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


def _collection_job(
    *,
    job_id: int = 12,
    status: str = "pending",
    saved_count: int = 0,
) -> dict[str, object]:
    return {
        "id": job_id,
        "source_url": "https://example.org/datasets/malaria-mortality",
        "kind": "repository_candidate",
        "repository_candidate_id": CANDIDATE_ID,
        "status": status,
        "saved_count": saved_count,
        "message": "Collection pending.",
        "error": "",
        "created_at": "2026-09-06 12:00:00",
        "updated_at": "2026-09-06 12:00:00",
        "finished_at": "",
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


def _use_pending_collection(monkeypatch) -> None:
    async def fake_reserve(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CollectionJobReservation(
            job=_collection_job(),
            created=True,
            already_collected=False,
        )

    monkeypatch.setattr(
        "app.routes.collector.get_candidate_collection",
        fake_reserve,
    )


def _use_candidate_persistence(monkeypatch, *, candidate=None) -> None:
    current = candidate or _candidate()

    async def fake_get(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return current

    async def fake_start(candidate_id, owner_id, *, retry=False):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        assert retry is False
        return {**current, "classification_status": "classifying"}

    async def fake_complete(candidate_id, owner_id, classification):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CandidateClassificationCompletion(
            _candidate(
                title=str(current["title"]), url=str(current["url"]),
                status="accepted" if classification.accepted else "rejected",
                classification=classification,
            ),
            await collector_routes.get_candidate_collection(candidate_id, owner_id)
            if classification.accepted else None,
        )

    monkeypatch.setattr("app.routes.collector.get_repository_candidate", fake_get)
    monkeypatch.setattr("app.routes.collector.start_candidate_classification", fake_start)
    monkeypatch.setattr(
        "app.routes.collector.complete_candidate_classification",
        fake_complete,
    )


def _use_search_persistence(monkeypatch) -> None:
    async def fake_create(query, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        return {"id": SEARCH_ID, "query": query}

    async def fake_complete(search_id, owner_id, **kwargs):
        assert search_id == SEARCH_ID
        assert owner_id == PRINCIPAL.owner_id
        return {"id": search_id, **kwargs}

    async def fake_save(search_id, owner_id, candidates, *, status):
        assert search_id == SEARCH_ID
        assert owner_id == PRINCIPAL.owner_id
        return [
            {
                **_candidate(title=item.title, url=item.url),
                "search_query": item.search_query,
                "source": item.source,
                "description": item.description,
            }
            for item in candidates
        ]

    monkeypatch.setattr("app.routes.collector.create_search_session", fake_create)
    monkeypatch.setattr("app.routes.collector.complete_search_session", fake_complete)
    monkeypatch.setattr(
        "app.routes.collector.complete_search_session_with_repository_candidates",
        fake_save,
    )


async def test_collector_search_datasets_returns_local_results_without_provider_call(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)

    async def fake_search_collected_datasets(query):
        assert query == "about malaria mortality in France"
        return [
            CollectedDataset(
                dataset_url="https://catalog.example.org/malaria",
                title="Malaria mortality data",
                description="Annual observations.",
                publisher="Public Health Institute",
                hosting_platform="CKAN",
                uploader="Epidemiology team",
                geography=("Senegal",),
                dataset_signals={"dataset": True},
                distributions=[
                    DistributionCandidate(
                        url="https://catalog.example.org/malaria.csv",
                        format="CSV",
                        probability=0.98,
                    )
                ],
                discovery_method="ckan",
                source_url="https://catalog.example.org",
                database_id=42,
            )
        ]

    def fail_if_provider_called(query):
        raise AssertionError(f"Provider called unexpectedly for {query!r}")

    monkeypatch.setattr(
        "app.routes.collector.search_collected_datasets",
        fake_search_collected_datasets,
    )
    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fail_if_provider_called,
    )

    response = await search_datasets(
        CollectorRepositorySearchRequest(query=" datasets about malaria mortality in France "),
        PRINCIPAL,
    )

    assert response.origin == "database"
    assert response.query == "datasets about malaria mortality in France"
    assert response.items[0].id == 42
    assert response.items[0].geography == ["Senegal"]
    assert response.items[0].distributions[0].format == "CSV"


async def test_collector_search_datasets_marks_session_error_when_local_completion_fails(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)
    completion_calls = []

    async def local_result(query):
        return [object()]

    async def fail_then_record(search_id, owner_id, **kwargs):
        completion_calls.append((search_id, owner_id, kwargs))
        if len(completion_calls) == 1:
            raise RuntimeError("Local completion unavailable")
        return {"id": search_id, **kwargs}

    monkeypatch.setattr("app.routes.collector.search_collected_datasets", local_result)
    monkeypatch.setattr("app.routes.collector.complete_search_session", fail_then_record)

    with pytest.raises(HTTPException) as error:
        await search_datasets(
            CollectorRepositorySearchRequest(query="malaria mortality"),
            PRINCIPAL,
        )

    assert error.value.status_code == 500
    assert completion_calls == [
        (SEARCH_ID, PRINCIPAL.owner_id, {"origin": "database"}),
        (
            SEARCH_ID,
            PRINCIPAL.owner_id,
            {
                "origin": "database",
                "status": "error",
                "error": "Local completion unavailable",
            },
        ),
    ]


async def test_collector_search_datasets_falls_back_online_when_database_is_empty(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)

    async def fake_search_collected_datasets(query):
        assert query == "about malaria mortality in France"
        return []

    def fake_search_repository_metadata(query):
        assert query == "datasets about malaria mortality in France"
        return RepositorySearchResponse(
            results=[
                RepositorySearchResult(
                    title="Online malaria dataset",
                    url="https://example.org/online-malaria",
                    source="DataCite",
                )
            ]
        )

    monkeypatch.setattr(
        "app.routes.collector.search_collected_datasets",
        fake_search_collected_datasets,
    )
    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fake_search_repository_metadata,
    )

    response = await search_datasets(
        CollectorRepositorySearchRequest(query="datasets about malaria mortality in France"),
        PRINCIPAL,
    )

    assert response.origin == "online"
    assert response.items[0].source == "DataCite"
    assert response.query == "datasets about malaria mortality in France"
    assert response.search_id == SEARCH_ID
    assert response.items[0].candidate_id == CANDIDATE_ID

    captured_queries = []

    class QueryCapturingClassifier:
        def classify(self, page):
            captured_queries.append(page.search_query)
            return RepositoryClassification(
                relevance_label="relevant",
                reason="The candidate matches the complete query.",
                ensemble=_accepted_repository_ensemble(
                    reason="The candidate matches the complete query."
                ),
            )

    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda: QueryCapturingClassifier(),
    )
    _use_candidate_persistence(
        monkeypatch,
        candidate=_candidate(
            title="Online malaria dataset",
            url="https://example.org/online-malaria",
            search_query="datasets about malaria mortality in France",
        ),
    )
    _use_pending_collection(monkeypatch)
    await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert captured_queries == ["datasets about malaria mortality in France"]


async def test_collector_search_datasets_marks_session_error_when_bounding_fails(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)
    completion_calls = []

    async def empty_database(query):
        return []

    def repository_result(query):
        return RepositorySearchResponse(
            results=[
                RepositorySearchResult(
                    title="Malaria dataset",
                    url="https://example.org/malaria",
                    source="DataCite",
                )
            ]
        )

    def fail_bounding(item, *, search_query):
        raise ValueError("Invalid provider metadata")

    async def record_completion(search_id, owner_id, **kwargs):
        completion_calls.append((search_id, owner_id, kwargs))
        return {"id": search_id, **kwargs}

    async def fail_if_candidates_saved(*args, **kwargs):
        raise AssertionError("Candidates must not be saved after bounding fails")

    monkeypatch.setattr("app.routes.collector.search_collected_datasets", empty_database)
    monkeypatch.setattr("app.routes.collector.search_repository_metadata", repository_result)
    monkeypatch.setattr("app.routes.collector._bounded_repository_result", fail_bounding)
    monkeypatch.setattr("app.routes.collector.complete_search_session", record_completion)
    monkeypatch.setattr(
        "app.routes.collector.complete_search_session_with_repository_candidates",
        fail_if_candidates_saved,
    )

    with pytest.raises(HTTPException) as error:
        await search_datasets(
            CollectorRepositorySearchRequest(query="malaria mortality"),
            PRINCIPAL,
        )

    assert error.value.status_code == 500
    assert completion_calls == [
        (
            SEARCH_ID,
            PRINCIPAL.owner_id,
            {
                "origin": "online",
                "status": "error",
                "error": "Invalid provider metadata",
            },
        )
    ]


async def test_collector_search_datasets_skips_local_search_for_generic_terms(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)

    async def fail_if_database_called(query):
        raise AssertionError(f"Database called unexpectedly for {query!r}")

    def fake_search_repository_metadata(query):
        assert query == "data datasets databases"
        return RepositorySearchResponse()

    monkeypatch.setattr(
        "app.routes.collector.search_collected_datasets",
        fail_if_database_called,
    )
    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fake_search_repository_metadata,
    )

    response = await search_datasets(
        CollectorRepositorySearchRequest(query="data datasets databases"),
        PRINCIPAL,
    )

    assert response.origin == "online"
    assert response.query == "data datasets databases"


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


async def test_collector_search_datasets_does_not_fallback_on_database_error(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)

    async def failing_database_search(query):
        raise RuntimeError("PostgreSQL unavailable")

    provider_called = False

    def fake_search_repository_metadata(query):
        nonlocal provider_called
        provider_called = True
        return RepositorySearchResponse()

    monkeypatch.setattr(
        "app.routes.collector.search_collected_datasets",
        failing_database_search,
    )
    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fake_search_repository_metadata,
    )

    with pytest.raises(HTTPException) as error:
        await search_datasets(
            CollectorRepositorySearchRequest(query="malaria mortality"),
            PRINCIPAL,
        )

    assert error.value.status_code == 500
    assert error.value.detail == "Database search failed."
    assert provider_called is False


async def test_collector_search_datasets_requires_non_blank_query():
    with pytest.raises(HTTPException) as error:
        await search_datasets(CollectorRepositorySearchRequest(query="   "), PRINCIPAL)

    assert error.value.status_code == 400
    assert error.value.detail == "Search query is required"


async def test_collector_search_quota_blocks_work_before_database_or_provider(
    monkeypatch,
):
    async def reject_quota(principal, operation):
        assert principal == PRINCIPAL
        assert operation == "repository_search"
        raise HTTPException(status_code=429, detail="quota exceeded")

    async def fail_if_session_created(query, owner_id):
        raise AssertionError(f"Session created unexpectedly for {query!r}, {owner_id!r}")

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", reject_quota)
    monkeypatch.setattr(
        "app.routes.collector.create_search_session",
        fail_if_session_created,
    )

    with pytest.raises(HTTPException) as error:
        await search_datasets(
            CollectorRepositorySearchRequest(query="malaria mortality"),
            PRINCIPAL,
        )

    assert error.value.status_code == 429


async def test_collector_classify_repository_result_route_returns_classification(
    monkeypatch,
):
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(monkeypatch)
    _use_pending_collection(monkeypatch)

    response = await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert response.title == "Malaria mortality estimates"
    assert response.classification is not None
    assert response.classification.accepted is True
    assert response.classification.relevance_label == "relevant"
    assert response.classification.reason == (
        "Malaria mortality estimates matches the search query."
    )
    assert response.automatic_collection is not None
    assert response.automatic_collection.state == "pending"
    assert response.automatic_collection.job is not None
    assert response.automatic_collection.job.id == 12


async def test_collector_classification_quota_blocks_llm_call(monkeypatch):
    _use_candidate_persistence(monkeypatch)

    async def reject_quota(principal, operation):
        assert principal == PRINCIPAL
        assert operation == "repository_classification"
        raise HTTPException(status_code=429, detail="quota exceeded")

    def fail_if_classifier_built():
        raise AssertionError("LLM classifier built after quota rejection")

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", reject_quota)
    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        fail_if_classifier_built,
    )

    with pytest.raises(HTTPException) as error:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert error.value.status_code == 429


async def test_collector_classify_rejected_result_does_not_create_collection_job(
    monkeypatch,
):
    class RejectingRepositoryClassifier:
        def classify(self, page):
            return RepositoryClassification(
                relevance_label="not_relevant",
                reason="The candidate does not match the query.",
                ensemble=_rejected_repository_ensemble(
                    reason="The candidate does not match the query."
                ),
            )

    async def fail_if_reserved(candidate_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        raise AssertionError(f"Rejected candidate reserved unexpectedly: {candidate_id}")

    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda: RejectingRepositoryClassifier(),
    )
    monkeypatch.setattr(
        "app.routes.collector.get_candidate_collection",
        fail_if_reserved,
    )
    _use_candidate_persistence(
        monkeypatch,
        candidate=_candidate(
            title="Unrelated dataset",
            url="https://example.org/datasets/unrelated",
        ),
    )

    response = await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert response.classification is not None
    assert response.classification.accepted is False
    assert response.automatic_collection is None


async def test_collector_classify_accepted_result_reuses_active_collection_job(
    monkeypatch,
):
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(monkeypatch)

    async def fake_reserve(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CollectionJobReservation(
            job=_collection_job(status="running"),
            created=False,
            already_collected=False,
        )

    monkeypatch.setattr(
        "app.routes.collector.get_candidate_collection",
        fake_reserve,
    )

    response = await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert response.automatic_collection is not None
    assert response.automatic_collection.state == "running"
    assert response.automatic_collection.job is not None
    assert response.automatic_collection.job.id == 12


async def test_collector_classify_accepted_saved_result_does_not_recollect(
    monkeypatch,
):
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(monkeypatch)

    async def fake_reserve(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CollectionJobReservation(
            job=None,
            created=False,
            already_collected=True,
        )

    monkeypatch.setattr(
        "app.routes.collector.get_candidate_collection",
        fake_reserve,
    )

    response = await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert response.automatic_collection is not None
    assert response.automatic_collection.state == "saved"
    assert response.automatic_collection.job is None


async def test_collector_classify_reports_failure_when_atomic_reservation_fails(monkeypatch):
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(monkeypatch)
    errors = []

    async def fail_completion(candidate_id, owner_id, classification):
        raise RuntimeError("Association insert failed")

    async def record_error(candidate_id, owner_id, error):
        errors.append((candidate_id, owner_id, error))

    monkeypatch.setattr("app.routes.collector.complete_candidate_classification", fail_completion)
    monkeypatch.setattr("app.routes.collector.fail_candidate_classification", record_error)
    with pytest.raises(HTTPException) as caught:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert caught.value.status_code == 500
    assert caught.value.detail == "Candidate classification could not be saved."
    assert errors == [(CANDIDATE_ID, PRINCIPAL.owner_id, "Association insert failed")]


async def test_collector_classify_repository_result_route_returns_502_when_classification_fails(
    monkeypatch,
    caplog,
):
    class FailingClassifier:
        def classify(self, page):
            raise PageClassificationError("LLM classification failed.")

    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda: FailingClassifier(),
    )
    _use_candidate_persistence(monkeypatch)
    recorded_errors = []

    async def fake_fail(candidate_id, owner_id, error):
        assert owner_id == PRINCIPAL.owner_id
        recorded_errors.append((candidate_id, error))
        return _candidate(status="error", error=error)

    monkeypatch.setattr("app.routes.collector.fail_candidate_classification", fake_fail)
    caplog.set_level("ERROR", logger="app.routes.collector")

    try:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL)
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Page classification failed."
        assert "DataCite" in caplog.text
        assert "https://example.org/datasets/malaria-mortality" in caplog.text
        assert "LLM classification failed." in caplog.text
        assert recorded_errors == [(CANDIDATE_ID, "LLM classification failed.")]
    else:
        raise AssertionError("Expected HTTPException.")


async def test_collector_classification_persistence_failure_marks_candidate_error(
    monkeypatch,
):
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(monkeypatch)
    recorded_errors = []

    async def fail_completion(candidate_id, owner_id, classification):
        raise RuntimeError("PostgreSQL write failed")

    async def record_failure(candidate_id, owner_id, error):
        recorded_errors.append((candidate_id, owner_id, error))
        return _candidate(status="error", error=error)

    monkeypatch.setattr(
        "app.routes.collector.complete_candidate_classification",
        fail_completion,
    )
    monkeypatch.setattr(
        "app.routes.collector.fail_candidate_classification",
        record_failure,
    )

    with pytest.raises(HTTPException) as error:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert error.value.status_code == 500
    assert error.value.detail == "Candidate classification could not be saved."
    assert recorded_errors == [
        (CANDIDATE_ID, PRINCIPAL.owner_id, "PostgreSQL write failed")
    ]


async def test_collector_repository_classification_limits_backend_concurrency(
    monkeypatch,
):
    active_calls = 0
    maximum_active_calls = 0
    counter_lock = threading.Lock()
    worker_pair = threading.Barrier(2)

    def fake_classify_one_repository_result(result, classifier):
        nonlocal active_calls, maximum_active_calls
        with counter_lock:
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)

        worker_pair.wait(timeout=1)
        time.sleep(0.02)

        with counter_lock:
            active_calls -= 1
        classification = RepositoryClassification(
            relevance_label="not_relevant",
            reason="Not relevant.",
            ensemble=_rejected_repository_ensemble(reason="Not relevant."),
        )
        return replace(result, classification=classification)

    monkeypatch.setattr(
        "app.routes.collector.classify_one_repository_result",
        fake_classify_one_repository_result,
    )
    monkeypatch.setattr(
        "app.routes.collector.build_default_repository_result_classifier",
        lambda: object(),
    )
    candidate_ids = [UUID(int=index + 10) for index in range(4)]

    async def fake_get(candidate_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        return {**_candidate(), "id": candidate_id}

    async def fake_start(candidate_id, owner_id, *, retry=False):
        assert owner_id == PRINCIPAL.owner_id
        return {**_candidate(status="classifying"), "id": candidate_id}

    async def fake_complete(candidate_id, owner_id, classification):
        assert owner_id == PRINCIPAL.owner_id
        return CandidateClassificationCompletion({
            **_candidate(status="rejected", classification=classification),
            "id": candidate_id,
        }, None)

    monkeypatch.setattr("app.routes.collector.get_repository_candidate", fake_get)
    monkeypatch.setattr("app.routes.collector.start_candidate_classification", fake_start)
    monkeypatch.setattr(
        "app.routes.collector.complete_candidate_classification",
        fake_complete,
    )

    await asyncio.gather(
        *(
            classify_repository_result(candidate_id, PRINCIPAL)
            for candidate_id in candidate_ids
        )
    )

    assert maximum_active_calls == 2


async def test_collector_classify_repository_result_returns_not_found(monkeypatch):
    async def fake_get(candidate_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        return None

    monkeypatch.setattr("app.routes.collector.get_repository_candidate", fake_get)

    with pytest.raises(HTTPException) as error:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert error.value.status_code == 404


async def test_collector_search_repositories_route_returns_bad_gateway_for_provider_errors(
    monkeypatch,
):
    _use_search_persistence(monkeypatch)

    async def empty_database(query):
        return []

    def fake_search_repository_metadata(query):
        raise ValueError("Could not fetch JSON URL: timeout")

    monkeypatch.setattr(
        "app.routes.collector.search_repository_metadata",
        fake_search_repository_metadata,
    )
    monkeypatch.setattr(
        "app.routes.collector.search_collected_datasets",
        empty_database,
    )

    try:
        await search_datasets(
            CollectorRepositorySearchRequest(query="malaria mortality"),
            PRINCIPAL,
        )
    except HTTPException as exception:
        assert exception.status_code == 502
        assert exception.detail == "Repository search failed."
    else:
        raise AssertionError("Expected HTTPException.")


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


def test_candidate_classification_request_rejects_browser_metadata():
    with pytest.raises(ValueError):
        CollectorRepositoryCandidateClassificationRequest(
            url="https://attacker.example/dataset",
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


async def test_collector_read_collection_job_route_returns_status(monkeypatch):
    async def fake_get_collection_job(job_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        assert job_id == 12
        return {
            "id": 12,
            "source_url": "https://catalog.example.org/",
            "status": "done",
            "saved_count": 2,
            "discovered_count": 10,
            "analyzed_count": 5,
            "accepted_count": 2,
            "rejected_count": 3,
            "invalid_distribution_count": 1,
            "discovery_methods": ["sitemap"],
            "message": "2 dataset(s) saved.",
            "error": "",
            "created_at": "2026-08-16 12:00:00",
            "updated_at": "2026-08-16 12:01:00",
            "finished_at": "2026-08-16 12:01:00",
        }

    monkeypatch.setattr(
        "app.routes.collector.get_collection_job_for_owner", fake_get_collection_job,
    )

    response = await read_collection_job(12, PRINCIPAL)

    assert response.job.id == 12
    assert response.job.status == "done"
    assert response.job.saved_count == 2
    assert response.job.discovered_count == 10
    assert response.job.discovery_methods == ["sitemap"]


async def test_collector_read_collection_job_route_returns_not_found(monkeypatch):
    async def fake_get_collection_job(job_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        return None

    monkeypatch.setattr(
        "app.routes.collector.get_collection_job_for_owner", fake_get_collection_job,
    )

    try:
        await read_collection_job(404, PRINCIPAL)
    except HTTPException as exception:
        assert exception.status_code == 404
        assert exception.detail == "Collection job not found"
    else:
        raise AssertionError("Expected HTTPException.")


@pytest.mark.parametrize("status,saved_count", [
    ("pending", 0), ("running", 0), ("done", 0), ("done", 2), ("error", 0),
])
@pytest.mark.parametrize("already_classified", [False, True])
async def test_job_public_view_is_identical_in_read_and_classification(
    monkeypatch, status, saved_count, already_classified,
):
    private_candidate = UUID("33333333-3333-4333-8333-333333333333")
    internal_error = "internal-only: password=example-secret host=private-db"
    stored_job = {
        **_collection_job(status=status, saved_count=saved_count),
        "repository_candidate_id": private_candidate,
        "message": internal_error,
        "error": internal_error,
        "internal_debug": internal_error,
    }
    original_job = deepcopy(stored_job)
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(
        monkeypatch,
        candidate=_candidate(status="accepted" if already_classified else "pending"),
    )
    if already_classified:
        async def already_reserved(*args, **kwargs):
            return None

        monkeypatch.setattr("app.routes.collector.start_candidate_classification", already_reserved)

    async def read_job(job_id, owner_id):
        assert job_id == stored_job["id"]
        assert owner_id == PRINCIPAL.owner_id
        return stored_job

    async def reserve_job(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CollectionJobReservation(stored_job, created=False, already_collected=False)

    monkeypatch.setattr("app.routes.collector.get_collection_job_for_owner", read_job)
    monkeypatch.setattr(
        "app.routes.collector.get_candidate_collection", reserve_job,
    )
    classified = await classify_repository_result(CANDIDATE_ID, PRINCIPAL)
    read = await read_collection_job(12, PRINCIPAL)
    job = classified.automatic_collection.job.model_dump(mode="json")

    assert job == read.job.model_dump(mode="json")
    assert "repository_candidate_id" not in job
    assert "internal_debug" not in job
    assert str(private_candidate) not in classified.model_dump_json()
    assert internal_error not in classified.model_dump_json()
    assert job["status"] == status
    assert job["saved_count"] == saved_count
    assert job["error_code"] == ("collection_failed" if status == "error" else "")
    assert job["error"] == ("Collection failed." if status == "error" else "")
    assert stored_job == original_job  # Public conversion must not erase the private diagnostic.


def test_candidate_errors_are_public_messages_and_keep_internal_diagnostics():
    stored = _candidate(status="error", error="internal-only: private provider response")
    public = _collector_repository_candidate(stored)

    assert public.classification_error == "Candidate classification failed."
    assert public.classification_error_code == "classification_failed"
    assert "internal-only" not in public.model_dump_json()
    assert stored["error"] == "internal-only: private provider response"


async def test_stored_classifier_vote_errors_are_sanitized_without_mutating_votes(monkeypatch):
    ensemble = _accepted_repository_ensemble(reason="Matches the query.")
    ensemble.update(
        successful_votes=2, accepted_votes=2, failed_votes=1,
        decision_voter_ids=["llm_a", "llm_b"],
        voters=ensemble["voters"][:2],
        failures=[{"voter_id": "llm_c", "error": "internal-only: credential details"}],
    )
    candidate = _candidate(status="accepted", classification=RepositoryClassification(
        relevance_label="relevant", reason="Matches the query.", ensemble=ensemble,
    ))
    original = deepcopy(candidate)
    _use_candidate_persistence(monkeypatch, candidate=candidate)

    async def no_new_classification(*args, **kwargs):
        return None

    async def already_saved(*args, **kwargs):
        return CollectionJobReservation(None, created=False, already_collected=True)

    monkeypatch.setattr(
        "app.routes.collector.start_candidate_classification", no_new_classification,
    )
    monkeypatch.setattr(
        "app.routes.collector.get_candidate_collection", already_saved,
    )
    response = await classify_repository_result(CANDIDATE_ID, PRINCIPAL)

    assert "internal-only" not in response.model_dump_json()
    assert response.classification.ensemble.failures[0].error == "Classifier vote failed."
    assert response.classification.ensemble.failures[0].error_code == "classifier_vote_failed"
    assert response.classification.ensemble.voters[0].reason == "Matches the query."
    assert candidate == original


def test_public_job_schema_does_not_advertise_private_candidate_id():
    from app.main import app

    properties = app.openapi()["components"]["schemas"]["CollectorCollectionJob"]["properties"]
    assert "repository_candidate_id" not in properties
    assert {"status", "saved_count", "source_url", "error_code"} <= properties.keys()


async def test_collector_list_collected_route_returns_saved_datasets(monkeypatch):
    async def fake_list_collected_datasets():
        return [
            CollectedDataset(
                dataset_url="https://catalog.example.org/dataset/mortality",
                title="Mortality health dataset",
                description="Official mortality health data.",
                publisher="National Health Agency",
                hosting_platform="",
                uploader="",
                geography=("France",),
                dataset_signals={},
                distributions=[],
                discovery_method="ckan",
                validation_results=[],
                source_url="https://catalog.example.org/",
                database_id=7,
                updated_at="2026-08-16 12:00:00",
            )
        ]

    monkeypatch.setattr(
        "app.routes.collector.list_collected_datasets",
        fake_list_collected_datasets,
    )

    response = await list_collected()

    assert len(response.items) == 1
    assert response.items[0].id == 7
    assert response.items[0].source_url == "https://catalog.example.org/"
    assert response.items[0].geography == ["France"]
    assert response.items[0].updated_at == "2026-08-16 12:00:00"


async def test_catalog_does_not_expose_persisted_vote_or_validation_exceptions(monkeypatch):
    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/mortality",
        title="Mortality dataset", description="Annual data", publisher="Health agency",
        hosting_platform="", uploader="", geography=(), distributions=[],
        dataset_signals={"ensemble": {
            "failed_votes": 1,
            "failures": [{"voter_id": "llm_c", "error": "internal-only: LLM failure"}],
        }},
        validation_results=[ValidationResult(
            url="https://catalog.example.org/data.csv",
            final_url="https://catalog.example.org/data.csv", format="CSV", ok=False,
            http_status=503, error="internal-only: HTTP failure",
        )],
    )
    original = deepcopy(dataset)

    async def list_datasets():
        return [dataset]

    monkeypatch.setattr("app.routes.collector.list_collected_datasets", list_datasets)
    response = await list_collected()

    assert "internal-only" not in response.model_dump_json()
    result = response.items[0]
    assert result.validation_results[0].http_status == 503
    assert result.validation_results[0].error_code == "validation_failed"
    failure = result.dataset_signals["ensemble"]["failures"][0]
    assert failure["error_code"] == "classifier_vote_failed"
    assert dataset == original
