"""Search snapshots preserve ownership and lifecycle without scheduling work."""
from uuid import uuid4

import pytest
from app.db import search_progress as store
from app.db.connection import _fetchall, _require_database_pool
from app.routes.collector import search_progress
from app.security import APIPrincipal
from fastapi import HTTPException, Response
from httpx import ASGITransport, AsyncClient
from test_classification_workflow import api, headers  # noqa: F401
from test_collection_workflow import candidate_for, decision

from collector.repository_search import RepositorySearchResult

pytestmark = pytest.mark.anyio


async def read(search_id, owner="alice"):
    response = Response()
    result = await search_progress(search_id, APIPrincipal(owner_id=owner), response)
    assert response.headers["cache-control"] == "no-store"
    return result


async def test_empty_and_missing_search_are_distinct(database):
    await database.init_database()
    search = await database.create_search_session("test", "alice")
    assert (await read(search["id"])).polling_required
    await database.complete_search_session(search["id"], "alice", origin="online")
    result = await read(search["id"])
    assert not result.polling_required and result.items == []
    for search_id, owner in [(search["id"], "bob"), (uuid4(), "alice")]:
        with pytest.raises(HTTPException) as error:
            await read(search_id, owner)
        assert error.value.status_code == 404


async def test_auth_and_shared_job_do_not_grant_access_to_another_search(database, api):  # noqa: F811
    await database.init_database()
    alice = await candidate_for(database)
    bob = await candidate_for(database, "bob")
    first = await database.complete_candidate_classification(alice["id"], "alice", decision())
    second = await database.complete_candidate_classification(bob["id"], "bob", decision())
    assert first.collection.job["id"] == second.collection.job["id"]
    path = f'/collector/searches/{alice["search_session_id"]}/progress'
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        denied = await client.get(path, headers=headers("bob"))
        absent = await client.get(f'/collector/searches/{uuid4()}/progress', headers=headers("bob"))
        assert denied.status_code == absent.status_code == 404
        assert denied.json() == absent.json()
        allowed = await client.get(path, headers=headers("alice"))
        assert allowed.status_code == 200
        assert [item["candidate_id"] for item in allowed.json()["items"]] == [str(alice["id"])]
        job_id = allowed.json()["items"][0]["automatic_collection"]["job"]["id"]
        assert job_id == first.collection.job["id"]


async def test_waits_for_collection_and_stops_on_error_without_leaking_diagnostics(database):
    await database.init_database()
    candidate = await candidate_for(database)
    sid = candidate["search_session_id"]
    await database.complete_search_session(sid, "alice", origin="online")
    assert (await read(sid)).polling_required
    completion = await database.complete_candidate_classification(
        candidate["id"], "alice", decision(),
    )
    assert (await read(sid)).polling_required
    job = await database.claim_pending_collection_job()
    assert job["id"] == completion.collection.job["id"]
    await database.mark_collection_job_error(job["id"], "private database password diagnostic")
    result = await read(sid)
    assert not result.polling_required
    assert "private database" not in result.model_dump_json()
    from app.db.collection_jobs import retry_collection_job_for_owner
    await retry_collection_job_for_owner(job["id"], "alice")
    assert (await read(sid)).polling_required


async def test_pending_and_rejected_candidates_need_no_polling(database):
    await database.init_database()
    candidate = await candidate_for(database)
    sid = candidate["search_session_id"]
    await database.complete_candidate_classification(candidate["id"], "alice", decision(False))
    await database.complete_search_session(sid, "alice", origin="online")
    assert not (await read(sid)).polling_required


@pytest.mark.parametrize("count", [1, 10])
async def test_query_count_is_constant_and_snapshot_does_not_mix_commits(
    database, monkeypatch, count,
):
    await database.init_database()
    search = await database.create_search_session("test", "alice")
    await database.save_repository_candidates(search["id"], "alice", [
        RepositorySearchResult(title=f"Data {i}", url=f"https://example.org/{i}", source="test")
        for i in range(count)
    ])
    await database.complete_search_session(search["id"], "alice", origin="online")
    counts = []
    original = store._fetchall

    async def observed(connection, sql, parameters=None):
        counts.append(sql)
        result = await original(connection, sql, parameters)
        if "FROM repository_candidates AS candidate" in sql:
            # Another connection commits after this snapshot has read candidates.
            async with _require_database_pool().connection() as writer:
                await writer.execute("UPDATE repository_candidates "
                                     "SET classification_status = 'queued' "
                                     "WHERE search_session_id = %s", (search["id"],))
        return result

    monkeypatch.setattr(store, "_fetchall", observed)
    result = await read(search["id"])
    assert len(result.items) == count
    assert all(item.classification_status == "pending" for item in result.items)
    assert not result.polling_required
    assert len(counts) == 4
    counts.clear()
    next_result = await read(search["id"])
    assert next_result.polling_required
    assert len(counts) == 4
    async with _require_database_pool().connection() as connection:
        assert await _fetchall(connection, "SELECT * FROM collection_jobs") == []
        assert await _fetchall(connection, "SELECT * FROM api_rate_limits") == []


async def test_saved_dataset_without_job_and_missing_legacy_followup(database):
    from app.db.repository_candidates import _complete_candidate_classification

    await database.init_database()
    candidate = await candidate_for(database)
    sid = candidate["search_session_id"]
    await database.complete_search_session(sid, "alice", origin="online")
    async with _require_database_pool().connection() as connection:
        await _complete_candidate_classification(connection, candidate["id"], "alice", decision())
    result = await read(sid)
    assert not result.polling_required
    assert result.items[0].automatic_collection.error_code == "collection_not_scheduled"
    async with _require_database_pool().connection() as connection:
        row = await connection.execute(
            "INSERT INTO collected_datasets (dataset_url, title) "
            "VALUES (%s, 'Mortality') RETURNING id",
            (candidate["url"],),
        )
        dataset_id = (await row.fetchone())["id"]
    result = await read(sid)
    assert result.items[0].automatic_collection.state == "saved"
    assert result.items[0].automatic_collection.job is None
    assert result.items[0].automatic_collection.dataset_ids == [dataset_id]


async def test_associated_job_and_dataset_ids_win_over_other_work_at_same_url(database):
    await database.init_database()
    alice = await candidate_for(database)
    first = await database.complete_candidate_classification(alice["id"], "alice", decision())
    job_id = first.collection.job["id"]
    await database.mark_collection_job_error(job_id, "failed")
    bob = await candidate_for(database, "bob")
    second = await database.complete_candidate_classification(bob["id"], "bob", decision())
    assert job_id != second.collection.job["id"]
    async with _require_database_pool().connection() as connection:
        row = await connection.execute(
            "INSERT INTO collected_datasets (dataset_url, title) VALUES (%s, 'Data') RETURNING id",
            (alice["url"],),
        )
        dataset_id = (await row.fetchone())["id"]
        await connection.execute(
            "INSERT INTO dataset_discovery_observations "
            "(collection_job_id, dataset_id, source_url) "
            "VALUES (%s, %s, %s)", (job_id, dataset_id, alice["url"]),
        )
    collection = (await read(alice["search_session_id"])).items[0].automatic_collection
    assert collection.job.id == job_id
    assert collection.state == "error"
    assert collection.dataset_ids == collection.job.dataset_ids == [dataset_id]
