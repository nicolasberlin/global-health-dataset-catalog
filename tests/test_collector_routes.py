from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from uuid import UUID

import pytest
from app.auth.security import APIPrincipal
from app.database import (
    CollectionJobReservation,
    normalize_dataset_search_query,
)
from app.quota_policy import QuotaExceeded
from app.routes.collector import (
    _collector_repository_candidate,
    classify_repository_result,
    list_collected,
    read_collection_job,
)
from app.routes.collector_schemas import (
    CollectorCollectedDataset,
    CollectorRepositoryCandidateClassificationRequest,
    CollectorRepositorySearchItem,
    CollectorRepositorySearchRequest,
)
from fastapi import HTTPException, Response
from helpers.workflows import CANDIDATE_ID
from helpers.workflows import collection_job as _collection_job

from collector.classification.repository import RepositoryClassification
from collector.storage.models import (
    CollectedDataset,
    DistributionCandidate,
    HTTPProbe,
    ValidationResult,
)
from collector.validation.downloads import validate_distribution

pytestmark = pytest.mark.anyio

SEARCH_ID = UUID("11111111-1111-4111-8111-111111111111")
PRINCIPAL = APIPrincipal(owner_id="test-user")


@pytest.fixture(autouse=True)
def bypass_api_quota(monkeypatch):
    _use_pending_collection(monkeypatch)


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
        "app.routes.candidates.get_candidate_collection",
        fake_reserve,
    )


def _use_candidate_persistence(monkeypatch, *, candidate=None) -> None:
    current = candidate or _candidate()

    async def fake_get(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return current

    async def fake_enqueue(candidate_id, owner_id, *, retry=False, admission=None):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        if current["classification_status"] == "pending" or (
            retry and current["classification_status"] == "error"
        ):
            current.update(classification_status="queued", classification=None, error="")
            return current
        return None

    monkeypatch.setattr("app.routes.candidates.get_repository_candidate", fake_get)
    monkeypatch.setattr("app.routes.candidates.enqueue_candidate_classification", fake_enqueue)


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


async def test_classification_request_returns_202_without_running_llm(monkeypatch):
    _use_candidate_persistence(monkeypatch)
    response = Response()
    result = await classify_repository_result(CANDIDATE_ID, PRINCIPAL, response)
    assert response.status_code == 202
    assert result.classification_status == "queued"
    assert result.classification is None
    assert result.automatic_collection is None


@pytest.mark.parametrize("status", ["queued", "classifying", "rejected", "error"])
async def test_repeated_classification_does_not_enqueue_or_charge_again(monkeypatch, status):
    _use_candidate_persistence(monkeypatch, candidate=_candidate(status=status))

    async def forbidden(*args, **kwargs):
        raise AssertionError("Must not enqueue or charge again")

    monkeypatch.setattr("app.routes.candidates.enqueue_candidate_classification", forbidden)
    if status == "error":
        with pytest.raises(HTTPException) as error:
            await classify_repository_result(CANDIDATE_ID, PRINCIPAL, Response())
        assert error.value.status_code == 409
    else:
        response = Response()
        result = await classify_repository_result(CANDIDATE_ID, PRINCIPAL, response)
        assert result.classification_status == status
        assert response.status_code == (202 if status in {"queued", "classifying"} else 200)


async def test_classification_maps_atomic_quota_rejection(monkeypatch):
    _use_candidate_persistence(monkeypatch)

    async def quota(*args, admission, **kwargs):
        assert admission.quotas[0].owner_id == PRINCIPAL.owner_id
        raise QuotaExceeded(11)

    monkeypatch.setattr("app.routes.candidates.enqueue_candidate_classification", quota)
    with pytest.raises(HTTPException) as error:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL, Response())
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "11"}


async def test_collector_classify_repository_result_returns_not_found(monkeypatch):
    async def fake_get(candidate_id, owner_id):
        assert owner_id == PRINCIPAL.owner_id
        return None

    monkeypatch.setattr("app.routes.candidates.get_repository_candidate", fake_get)

    with pytest.raises(HTTPException) as error:
        await classify_repository_result(CANDIDATE_ID, PRINCIPAL, Response())

    assert error.value.status_code == 404


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
        "app.routes.collection_jobs.get_collection_job_for_owner",
        fake_get_collection_job,
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
        "app.routes.collection_jobs.get_collection_job_for_owner",
        fake_get_collection_job,
    )

    try:
        await read_collection_job(404, PRINCIPAL)
    except HTTPException as exception:
        assert exception.status_code == 404
        assert exception.detail == "Collection job not found"
    else:
        raise AssertionError("Expected HTTPException.")


@pytest.mark.parametrize(
    "status,saved_count",
    [
        ("pending", 0),
        ("running", 0),
        ("done", 0),
        ("done", 2),
        ("error", 0),
    ],
)
async def test_job_public_view_is_identical_in_read_and_classification(
    monkeypatch,
    status,
    saved_count,
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
    _use_candidate_persistence(
        monkeypatch,
        candidate=_candidate(status="accepted"),
    )

    async def read_job(job_id, owner_id):
        assert job_id == stored_job["id"]
        assert owner_id == PRINCIPAL.owner_id
        return stored_job

    async def reserve_job(candidate_id, owner_id):
        assert candidate_id == CANDIDATE_ID
        assert owner_id == PRINCIPAL.owner_id
        return CollectionJobReservation(stored_job, created=False, already_collected=False)

    monkeypatch.setattr("app.routes.collection_jobs.get_collection_job_for_owner", read_job)
    monkeypatch.setattr(
        "app.routes.candidates.get_candidate_collection",
        reserve_job,
    )
    classified = await classify_repository_result(CANDIDATE_ID, PRINCIPAL, Response())
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
        successful_votes=2,
        accepted_votes=2,
        failed_votes=1,
        decision_voter_ids=["llm_a", "llm_b"],
        voters=ensemble["voters"][:2],
        failures=[{"voter_id": "llm_c", "error": "internal-only: credential details"}],
    )
    candidate = _candidate(
        status="accepted",
        classification=RepositoryClassification(
            relevance_label="relevant",
            reason="Matches the query.",
            ensemble=ensemble,
        ),
    )
    original = deepcopy(candidate)
    _use_candidate_persistence(monkeypatch, candidate=candidate)

    async def no_new_classification(*args, **kwargs):
        return None

    async def already_saved(*args, **kwargs):
        return CollectionJobReservation(None, created=False, already_collected=True)

    monkeypatch.setattr(
        "app.routes.candidates.enqueue_candidate_classification",
        no_new_classification,
    )
    monkeypatch.setattr(
        "app.routes.candidates.get_candidate_collection",
        already_saved,
    )
    response = await classify_repository_result(CANDIDATE_ID, PRINCIPAL, Response())

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
    async def fake_list_collected_datasets(**kwargs):
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
        "app.routes.catalog.list_collected_datasets",
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
        title="Mortality dataset",
        description="Annual data",
        publisher="Health agency",
        hosting_platform="",
        uploader="",
        geography=(),
        distributions=[],
        dataset_signals={
            "ensemble": {
                "failed_votes": 1,
                "failures": [{"voter_id": "llm_c", "error": "internal-only: LLM failure"}],
            }
        },
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/data.csv",
                final_url="https://catalog.example.org/data.csv",
                format="CSV",
                ok=False,
                http_status=503,
                error="internal-only: HTTP failure",
            )
        ],
    )
    original = deepcopy(dataset)

    async def list_datasets(**kwargs):
        return [dataset]

    monkeypatch.setattr("app.routes.catalog.list_collected_datasets", list_datasets)
    response = await list_collected()

    assert "internal-only" not in response.model_dump_json()
    result = response.items[0]
    assert result.validation_results[0].http_status == 503
    assert result.validation_results[0].error_code == "validation_failed"
    failure = result.dataset_signals["ensemble"]["failures"][0]
    assert failure["error_code"] == "classifier_vote_failed"
    assert dataset == original


@pytest.mark.parametrize(
    "code,body,status",
    [
        (401, b"", "restricted"),
        (403, b"", "unconfirmed"),
        (403, b"<html>Authentication required</html>", "restricted"),
        (200, b'<html><form><input type="password"></form></html>', "restricted"),
        (200, b"<html>CAPTCHA</html>", "unconfirmed"),
    ],
)
async def test_catalog_preserves_access_diagnosis(monkeypatch, code, body, status):
    distribution = DistributionCandidate("https://example.org/data.csv", "CSV", 0.9)
    validation = validate_distribution(
        distribution,
        probe=lambda url, method, **kw: HTTPProbe(
            url,
            url,
            code,
            {"content-type": "text/html"},
            body if method == "GET" else b"",
            error="internal-only: HTTP failure" if code >= 400 else "",
        ),
    )
    dataset = CollectedDataset(
        dataset_url="https://example.org/dataset",
        title="Health",
        description="",
        publisher="",
        hosting_platform="",
        uploader="",
        dataset_signals={},
        distributions=[distribution],
        validation_results=[validation],
    )

    async def list_datasets(**kwargs):
        return [dataset]

    monkeypatch.setattr("app.routes.catalog.list_collected_datasets", list_datasets)
    response = await list_collected()
    public = response.items[0].validation_results[0]
    assert public.status == validation.status == status
    assert public.reason == validation.reason
    assert public.ok is False
    assert "internal-only" not in response.model_dump_json()
