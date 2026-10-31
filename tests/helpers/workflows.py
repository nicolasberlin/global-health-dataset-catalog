"""Shared API and persisted-workflow test setup."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from app.api.routes.searches import get_search_progress
from app.auth.security import APIPrincipal
from app.db.connection import _fetchall, _require_database_pool
from fastapi import Response

from collector.classification.repository import RepositoryClassification
from collector.repository_search import RepositorySearchResult

SOURCE_URL = "https://repository.example.org/mortality"


CANDIDATE_ID = UUID("22222222-2222-4222-8222-222222222222")


def decision(accepted=True, *, reason="Test decision.", voter_reason=None):
    label = "relevant" if accepted else "not_relevant"
    return RepositoryClassification(
        relevance_label=label,
        reason=reason,
        ensemble={
            "votes_required": 2,
            "minimum_successful_votes": 3,
            "successful_votes": 3,
            "failed_votes": 0,
            "accepted_votes": 3 if accepted else 0,
            "decision": "accepted" if accepted else "rejected",
            "decision_reason": "enough_accept_votes" if accepted else "rejected_by_majority",
            "decision_voter_ids": ["a", "b", "c"],
            "failures": [],
            "voters": [
                {
                    "voter_id": voter,
                    "accepted": accepted,
                    "relevance_label": label,
                    "reason": reason if voter_reason is None else voter_reason,
                    "missing_information": [],
                }
                for voter in ("a", "b", "c")
            ],
        },
    )


def classification_decision(accepted=True):
    return decision(accepted, reason="Matches the persisted query.", voter_reason="Matches.")


async def start_candidate(database, candidate_id, owner_id):
    """Prepare an initial worker claim without using the optional command API."""
    async with _require_database_pool().connection() as connection:
        row = await connection.execute(
            "UPDATE repository_candidates AS candidate SET classification_status = 'queued' "
            "FROM search_sessions AS session WHERE candidate.id = %s "
            "AND candidate.search_session_id = session.id AND session.owner_id = %s "
            "AND candidate.classification_status = 'pending' RETURNING candidate.id",
            (candidate_id, owner_id),
        )
        if await row.fetchone() is None:
            return None
    return await database.claim_candidate_classification()


async def candidate(database, owner="alice", query="mortality", *, url="https://example.org/data"):
    search = await database.create_search_session(query, owner)
    items = await database.save_repository_candidates(
        search["id"],
        owner,
        [RepositorySearchResult(title="Mortality", url=url, source="DataCite")],
    )
    return items[0]


async def candidate_for(database, owner="alice", url=SOURCE_URL):
    item = await candidate(database, owner, url=url)
    await start_candidate(database, item["id"], owner)
    return item


async def rows(query):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, query)


async def wait_until(check):
    async def poll():
        while not await check():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=5)


def headers(owner="alice"):
    return {"X-Test-Owner": owner}


async def read(search_id, owner="alice"):
    response = Response()
    result = await get_search_progress(search_id, APIPrincipal(owner_id=owner), response)
    assert response.headers["cache-control"] == "no-store"
    return result


async def claimed(database):
    await database.init_database()
    candidate = await candidate_for(database)
    accepted = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job = await database.claim_pending_collection_job()
    assert job["id"] == accepted.collection.job["id"]
    return job, datetime.fromisoformat(job["updated_at"])


def observation(status="succeeded"):
    return {
        "method": "browser",
        "status": status,
        "http_status": 200,
        "requested_url": "https://example.org/data?token=secret",
        "final_url": "https://example.org/data?fileId=1&token=secret",
        "html": "DO NOT STORE",
        "cookies": {"auth": "DO NOT STORE"},
        "code": "repository_metadata_invalid",
        "failure_phase": "normalize",
        "reason": "DO NOT STORE",
        "checks": [
            {
                "resource_key": "file:1",
                "url": "https://example.org/file?token=secret",
                "format": "CSV",
                "status": "available",
                "http_status": 206,
            }
        ],
    }


def collection_job(
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
