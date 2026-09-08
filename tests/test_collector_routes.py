from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import asdict, replace
from uuid import UUID

import pytest
from app.database import CollectionJobReservation, normalize_dataset_search_query
from app.routes.collector import (
    _run_collection_job,
    classify_repository_result,
    list_collected,
    read_collection_job,
    search_datasets,
    start_collection_job,
)
from app.routes.collector_schemas import (
    CollectorCollectedDataset,
    CollectorRepositoryCandidateClassificationRequest,
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
    CollectorURLRequest,
)
from app.security import APIPrincipal
from fastapi import BackgroundTasks, HTTPException

from collector.classification.page import PageClassificationError
from collector.classification.repository import RepositoryClassification
from collector.repository_search import (
    RepositorySearchResponse,
    RepositorySearchResult,
)
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
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
            "collection_start",
        }

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", allow_request)


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
        "message": "Collecte en attente.",
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


def _use_new_automatic_collection_reservation(monkeypatch) -> None:
    async def fake_reserve(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CollectionJobReservation(
            job=_collection_job(),
            created=True,
            already_collected=False,
        )

    monkeypatch.setattr(
        "app.routes.collector.reserve_repository_candidate_collection_job",
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
        return _candidate(
            title=str(current["title"]),
            url=str(current["url"]),
            status="accepted" if classification.accepted else "rejected",
            classification=classification,
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
    _use_new_automatic_collection_reservation(monkeypatch)
    await classify_repository_result(CANDIDATE_ID, BackgroundTasks(), PRINCIPAL)

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
    _use_new_automatic_collection_reservation(monkeypatch)
    background_tasks = BackgroundTasks()

    response = await classify_repository_result(CANDIDATE_ID, background_tasks, PRINCIPAL)

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
    assert len(background_tasks.tasks) == 1


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
        await classify_repository_result(CANDIDATE_ID, BackgroundTasks(), PRINCIPAL)

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
        "app.routes.collector.reserve_repository_candidate_collection_job",
        fail_if_reserved,
    )
    _use_candidate_persistence(
        monkeypatch,
        candidate=_candidate(
            title="Unrelated dataset",
            url="https://example.org/datasets/unrelated",
        ),
    )
    background_tasks = BackgroundTasks()

    response = await classify_repository_result(CANDIDATE_ID, background_tasks, PRINCIPAL)

    assert response.classification is not None
    assert response.classification.accepted is False
    assert response.automatic_collection is None
    assert background_tasks.tasks == []


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
        "app.routes.collector.reserve_repository_candidate_collection_job",
        fake_reserve,
    )
    background_tasks = BackgroundTasks()

    response = await classify_repository_result(CANDIDATE_ID, background_tasks, PRINCIPAL)

    assert response.automatic_collection is not None
    assert response.automatic_collection.state == "running"
    assert response.automatic_collection.job is not None
    assert response.automatic_collection.job.id == 12
    assert background_tasks.tasks == []


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
        "app.routes.collector.reserve_repository_candidate_collection_job",
        fake_reserve,
    )
    background_tasks = BackgroundTasks()

    response = await classify_repository_result(CANDIDATE_ID, background_tasks, PRINCIPAL)

    assert response.automatic_collection is not None
    assert response.automatic_collection.state == "saved"
    assert response.automatic_collection.job is None
    assert background_tasks.tasks == []


async def test_collector_classify_keeps_acceptance_when_collection_reservation_fails(
    monkeypatch,
):
    _use_accepting_repository_classifier(monkeypatch)
    _use_candidate_persistence(monkeypatch)

    async def fail_reservation(candidate_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        raise RuntimeError(f"Database unavailable for {candidate_id}")

    monkeypatch.setattr(
        "app.routes.collector.reserve_repository_candidate_collection_job",
        fail_reservation,
    )
    background_tasks = BackgroundTasks()

    response = await classify_repository_result(CANDIDATE_ID, background_tasks, PRINCIPAL)

    assert response.classification is not None
    assert response.classification.accepted is True
    assert response.automatic_collection is not None
    assert response.automatic_collection.state == "error"
    assert response.automatic_collection.error == ("Automatic collection scheduling failed.")
    assert background_tasks.tasks == []


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
        await classify_repository_result(CANDIDATE_ID, BackgroundTasks(), PRINCIPAL)
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
        await classify_repository_result(CANDIDATE_ID, BackgroundTasks(), PRINCIPAL)

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
        return {
            **_candidate(status="rejected", classification=classification),
            "id": candidate_id,
        }

    monkeypatch.setattr("app.routes.collector.get_repository_candidate", fake_get)
    monkeypatch.setattr("app.routes.collector.start_candidate_classification", fake_start)
    monkeypatch.setattr(
        "app.routes.collector.complete_candidate_classification",
        fake_complete,
    )

    await asyncio.gather(
        *(
            classify_repository_result(candidate_id, BackgroundTasks(), PRINCIPAL)
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
        await classify_repository_result(CANDIDATE_ID, BackgroundTasks(), PRINCIPAL)

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


async def test_collector_start_collection_job_route_enqueues_background_task(monkeypatch):
    async def fake_create_collection_job(source_url):
        assert source_url == "https://catalog.example.org/"
        return {
            "id": 12,
            "source_url": source_url,
            "status": "pending",
            "saved_count": 0,
            "message": "Collecte en attente.",
            "error": "",
            "created_at": "2026-08-16 12:00:00",
            "updated_at": "2026-08-16 12:00:00",
            "finished_at": "",
        }

    background_tasks = BackgroundTasks()

    monkeypatch.setattr(
        "app.routes.collector.db_create_collection_job",
        fake_create_collection_job,
    )

    response = await start_collection_job(
        CollectorURLRequest(url="https://catalog.example.org"),
        background_tasks,
        PRINCIPAL,
    )

    assert response.job.id == 12
    assert response.job.status == "pending"
    assert len(background_tasks.tasks) == 1


async def test_collector_read_collection_job_route_returns_status(monkeypatch):
    async def fake_get_collection_job(job_id):
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
            "message": "2 dataset(s) sauvegardé(s).",
            "error": "",
            "created_at": "2026-08-16 12:00:00",
            "updated_at": "2026-08-16 12:01:00",
            "finished_at": "2026-08-16 12:01:00",
        }

    monkeypatch.setattr("app.routes.collector.get_collection_job", fake_get_collection_job)

    response = await read_collection_job(12, PRINCIPAL)

    assert response.job.id == 12
    assert response.job.status == "done"
    assert response.job.saved_count == 2
    assert response.job.discovered_count == 10
    assert response.job.discovery_methods == ["sitemap"]


async def test_collector_read_collection_job_route_returns_not_found(monkeypatch):
    async def fake_get_collection_job(job_id):
        return None

    monkeypatch.setattr("app.routes.collector.get_collection_job", fake_get_collection_job)

    try:
        await read_collection_job(404, PRINCIPAL)
    except HTTPException as exception:
        assert exception.status_code == 404
        assert exception.detail == "Collection job not found"
    else:
        raise AssertionError("Expected HTTPException.")


async def test_run_collection_job_marks_done(monkeypatch):
    calls = []

    def fake_collect_source_with_report(source_url):
        calls.append(("collect", source_url))
        return CollectionResult(
            datasets=[
                CollectedDataset(
                    dataset_url="https://catalog.example.org/dataset/mortality",
                    title="Mortality health dataset",
                    description="Official mortality health data.",
                    publisher="National Health Agency",
                    hosting_platform="",
                    uploader="",
                    dataset_signals={},
                    distributions=[],
                    discovery_method="ckan",
                    validation_results=[],
                )
            ],
            report=CollectionReport(
                discovered_count=5,
                analyzed_count=5,
                accepted_count=1,
                rejected_count=4,
                invalid_distribution_count=1,
                discovery_methods=("ckan",),
            ),
        )

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return {"id": job_id, "status": "running"}

    async def fake_complete_collection_job(job_id, collection_result):
        calls.append(
            (
                "complete",
                job_id,
                len(collection_result.datasets),
                collection_result.report.discovered_count,
                collection_result.report.discovery_methods,
            )
        )

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.complete_collection_job",
        fake_complete_collection_job,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [
        ("running", 12),
        ("collect", "https://catalog.example.org/"),
        ("complete", 12, 1, 5, ("ckan",)),
    ]


async def test_run_automatic_collection_job_uses_candidate_pipeline_and_completes_empty(
    monkeypatch,
):
    calls = []

    def fake_collect_repository_candidate_with_report(source_url):
        calls.append(("collect_candidate", source_url))
        return CollectionResult(
            report=CollectionReport(
                discovered_count=1,
                analyzed_count=1,
                rejected_count=1,
                invalid_distribution_count=1,
                discovery_methods=("repository_search",),
            )
        )

    def fail_if_source_collection_runs(source_url):
        raise AssertionError(f"Whole-source collection ran unexpectedly: {source_url}")

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return {"id": job_id, "status": "running"}

    async def fake_complete_collection_job(job_id, collection_result):
        calls.append(
            (
                "complete",
                job_id,
                len(collection_result.datasets),
                collection_result.report.discovery_methods,
            )
        )

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_repository_candidate_with_report",
        fake_collect_repository_candidate_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fail_if_source_collection_runs,
    )
    monkeypatch.setattr(
        "app.routes.collector.complete_collection_job",
        fake_complete_collection_job,
    )

    await _run_collection_job(
        12,
        "https://example.org/datasets/malaria-mortality",
        repository_candidate=True,
    )

    assert calls == [
        ("running", 12),
        (
            "collect_candidate",
            "https://example.org/datasets/malaria-mortality",
        ),
        ("complete", 12, 0, ("repository_search",)),
    ]


async def test_run_collection_job_stops_when_job_cannot_be_started(monkeypatch):
    calls = []

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return None

    def fake_collect_source_with_report(source_url):
        calls.append(("collect", source_url))
        raise AssertionError("Collection should not run for a stale job.")

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [("running", 12)]


async def test_run_collection_job_marks_errors(monkeypatch):
    calls = []

    def fake_collect_source_with_report(source_url):
        raise ValueError("bad source")

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return {"id": job_id, "status": "running"}

    async def fake_mark_collection_job_error(job_id, error):
        calls.append(("error", job_id, error))

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_error",
        fake_mark_collection_job_error,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [("running", 12), ("error", 12, "bad source")]


async def test_collection_jobs_limit_backend_concurrency(monkeypatch):
    active_calls = 0
    maximum_active_calls = 0
    counter_lock = threading.Lock()
    worker_pair = threading.Barrier(2)

    def fake_collect_source_with_report(source_url):
        nonlocal active_calls, maximum_active_calls
        with counter_lock:
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)

        worker_pair.wait(timeout=1)
        time.sleep(0.02)

        with counter_lock:
            active_calls -= 1
        return CollectionResult()

    async def fake_mark_collection_job_running(job_id):
        return {"id": job_id, "status": "running"}

    async def fake_complete_collection_job(job_id, collection_result):
        return {"id": job_id, "status": "done"}

    async def fail_if_marked_error(job_id, error):
        raise AssertionError(f"Job {job_id} failed unexpectedly: {error}")

    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.complete_collection_job",
        fake_complete_collection_job,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_error",
        fail_if_marked_error,
    )

    await asyncio.gather(
        *(
            _run_collection_job(job_id, f"https://catalog.example.org/{job_id}")
            for job_id in range(1, 5)
        )
    )

    assert maximum_active_calls == 2


async def test_run_collection_job_marks_error_when_completion_fails(monkeypatch):
    calls = []

    def fake_collect_source_with_report(source_url):
        calls.append(("collect", source_url))
        return CollectionResult()

    async def fake_mark_collection_job_running(job_id):
        calls.append(("running", job_id))
        return {"id": job_id, "status": "running"}

    async def fake_complete_collection_job(job_id, collection_result):
        calls.append(("complete", job_id, len(collection_result.datasets)))
        raise RuntimeError("database write failed")

    async def fake_mark_collection_job_error(job_id, error):
        calls.append(("error", job_id, error))

    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_running",
        fake_mark_collection_job_running,
    )
    monkeypatch.setattr(
        "app.routes.collector.collect_source_with_report",
        fake_collect_source_with_report,
    )
    monkeypatch.setattr(
        "app.routes.collector.complete_collection_job",
        fake_complete_collection_job,
    )
    monkeypatch.setattr(
        "app.routes.collector.mark_collection_job_error",
        fake_mark_collection_job_error,
    )

    await _run_collection_job(12, "https://catalog.example.org/")

    assert calls == [
        ("running", 12),
        ("collect", "https://catalog.example.org/"),
        ("complete", 12, 0),
        ("error", 12, "database write failed"),
    ]


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
