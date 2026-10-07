"""Worker acquisition receipts survive lost commits without changing queue ownership."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from uuid import uuid4

import pytest
from app import workers
from app.db import collection_jobs, repository_candidates, search_jobs
from app.db.connection import _require_database_pool
from app.db.task_retries import schedule_llm_retry
from psycopg import OperationalError

from collector.classification.repository import RepositoryClassification
from collector.diagnostics import Diagnostic
from collector.repository_search import RepositorySearchResult

pytestmark = pytest.mark.anyio
QUEUES = ("search", "classification", "collection")
MODULES = {
    "search": search_jobs,
    "classification": repository_candidates,
    "collection": collection_jobs,
}
CLAIMS = {
    "search": "claim_search",
    "classification": "claim_candidate_classification",
    "collection": "claim_pending_collection_job",
}
TABLES = {
    "search": "search_sessions",
    "classification": "repository_candidates",
    "collection": "collection_jobs",
}
STATUS_COLUMNS = {
    "search": "status",
    "classification": "classification_status",
    "collection": "status",
}
QUEUED = {"search": "queued", "classification": "queued", "collection": "pending"}
RUNNING = {"search": "running", "classification": "classifying", "collection": "running"}


async def sql(query, params=None):
    async with _require_database_pool().connection() as connection:
        cursor = await connection.execute(query, params)
        return await cursor.fetchall() if cursor.description else []


def claim_for(queue):
    return getattr(MODULES[queue], CLAIMS[queue])


def version(item):
    value = item["updated_at"]
    return datetime.fromisoformat(value) if isinstance(value, str) else value


async def receipts(queue):
    return await sql("SELECT * FROM worker_claims WHERE queue = %s", (queue,))


async def persisted(queue, item):
    return (await sql(f"SELECT * FROM {TABLES[queue]} WHERE id = %s", (item["id"],)))[0]


async def enqueue(database, queue):
    suffix = uuid4().hex
    if queue == "search":
        item, _ = await search_jobs.admit_search(
            "alice",
            suffix,
            query="mortality",
            access_mode="local",
            client_key=None,
        )
        return item
    session = await database.create_search_session("mortality", "alice")
    item = (
        await database.save_repository_candidates(
            session["id"],
            "alice",
            [
                RepositorySearchResult(
                    title="Mortality",
                    url=f"https://example.org/{suffix}",
                    source="test",
                )
            ],
        )
    )[0]
    await database.enqueue_candidate_classification(item["id"], "alice")
    if queue == "classification":
        return item
    claimed = await repository_candidates.claim_candidate_classification()
    assert claimed["id"] == item["id"]
    result = await database.complete_candidate_classification(
        item["id"],
        "alice",
        RepositoryClassification("relevant", "Health dataset."),
    )
    return result.collection.job


async def fail(database, queue, item):
    if queue == "search":
        await search_jobs.fail_discovery(
            item,
            origin="online",
            error="Interrupted.",
            diagnostics=[],
        )
    elif queue == "classification":
        await database.fail_candidate_classification(item["id"], "alice", "Interrupted.")
    else:
        await database.mark_collection_job_error(item["id"], "Interrupted.")


async def manual_retry(database, queue, item):
    await fail(database, queue, item)
    if queue == "search":
        await search_jobs.admit_search(
            "alice",
            uuid4().hex,
            access_mode="local",
            client_key=None,
            retry_search_id=item["id"],
        )
    elif queue == "classification":
        await database.enqueue_candidate_classification(item["id"], "alice", retry=True)
    else:
        await collection_jobs.retry_collection_job_for_owner(item["id"], "alice")


@pytest.mark.parametrize("queue", QUEUES)
async def test_consumer_recovers_lost_claim_ack_without_claiming_or_executing_other_work(
    database,
    monkeypatch,
    queue,
):
    await database.init_database()
    first = await enqueue(database, queue)
    second = await enqueue(database, queue)
    actual_claim = claim_for(queue)
    tokens, claimed_items, executions = [], [], []
    stop = asyncio.Event()

    async def lost_ack(*, claim_token):
        tokens.append(claim_token)
        item = await actual_claim(claim_token=claim_token)
        claimed_items.append(item)
        if len(tokens) == 1:
            # The real SQL transaction has committed; only its acknowledgement is lost.
            assert (await persisted(queue, item))[STATUS_COLUMNS[queue]] == RUNNING[queue]
            raise OperationalError("Connection lost after claim commit.")
        return item

    async def execute(item, executor):
        executions.append(item["id"])
        await fail(database, queue, item)
        stop.set()

    monkeypatch.setattr(
        workers,
        "persist_with_retry",
        partial(workers.persist_with_retry, initial_delay=0),
    )
    with ThreadPoolExecutor(1) as executor:
        await asyncio.wait_for(workers._consume(stop, executor, 0.001, lost_ack, execute), 3)
    assert len(tokens) == 2 and tokens[0] == tokens[1]
    assert claimed_items[0]["id"] == claimed_items[1]["id"] == first["id"]
    assert version(claimed_items[0]) == version(claimed_items[1])
    assert executions == [first["id"]]
    assert (await persisted(queue, second))[STATUS_COLUMNS[queue]] == QUEUED[queue]
    assert len(await receipts(queue)) == 1


@pytest.mark.parametrize("queue", QUEUES)
async def test_concurrent_same_token_returns_one_receipt_and_same_attempt(database, queue):
    await database.init_database()
    first = await enqueue(database, queue)
    second = await enqueue(database, queue)
    token = uuid4()
    results = await asyncio.gather(*[claim_for(queue)(claim_token=token) for _ in range(4)])
    assert {str(item["id"]) for item in results} == {str(first["id"])}
    assert len({version(item) for item in results}) == 1
    assert len(await receipts(queue)) == 1
    assert (await persisted(queue, second))[STATUS_COLUMNS[queue]] == QUEUED[queue]
    if queue == "search":
        assert len({item["attempt_token"] for item in results}) == 1


@pytest.mark.parametrize("queue", QUEUES)
async def test_concurrent_distinct_tokens_claim_distinct_work(database, queue):
    await database.init_database()
    items = [await enqueue(database, queue) for _ in range(3)]
    results = await asyncio.gather(*[claim_for(queue)(claim_token=uuid4()) for _ in items])
    assert {str(item["id"]) for item in results} == {str(item["id"]) for item in items}
    assert len(await receipts(queue)) == len(items)


@pytest.mark.parametrize("queue", QUEUES)
async def test_receipt_failure_rolls_back_queue_update_and_receipt(database, monkeypatch, queue):
    await database.init_database()
    item = await enqueue(database, queue)
    token = uuid4()
    original = MODULES[queue].record_worker_claim

    async def rollback(*args, **kwargs):
        await original(*args, **kwargs)
        raise OperationalError("Rollback before claim transaction commits.")

    with monkeypatch.context() as patch:
        patch.setattr(MODULES[queue], "record_worker_claim", rollback)
        with pytest.raises(OperationalError):
            await claim_for(queue)(claim_token=token)
    assert (await persisted(queue, item))[STATUS_COLUMNS[queue]] == QUEUED[queue]
    assert await receipts(queue) == []
    result = await claim_for(queue)(claim_token=token)
    assert result["id"] == item["id"]
    assert len(await receipts(queue)) == 1


@pytest.mark.parametrize("queue", QUEUES)
async def test_empty_poll_does_not_accumulate_receipts(database, queue):
    await database.init_database()
    token = uuid4()
    for _ in range(3):
        assert await claim_for(queue)(claim_token=token) is None
    assert await receipts(queue) == []
    item = await enqueue(database, queue)
    assert (await claim_for(queue)(claim_token=token))["id"] == item["id"]
    assert len(await receipts(queue)) == 1


@pytest.mark.parametrize("queue", QUEUES)
async def test_old_receipt_cannot_claim_requeued_attempt_or_unrelated_work(database, queue):
    await database.init_database()
    await enqueue(database, queue)
    old_token = uuid4()
    old = await claim_for(queue)(claim_token=old_token)
    await manual_retry(database, queue, old)
    assert await claim_for(queue)(claim_token=old_token) is None
    current = await claim_for(queue)(claim_token=uuid4())
    assert current["id"] == old["id"] and version(current) != version(old)
    other = await enqueue(database, queue)
    assert await claim_for(queue)(claim_token=old_token) is None
    assert (await persisted(queue, other))[STATUS_COLUMNS[queue]] == QUEUED[queue]
    assert len(await receipts(queue)) == 2


@pytest.mark.parametrize("queue", ("classification", "collection"))
async def test_automatic_retry_respects_due_date_and_fences_old_receipt(database, queue):
    await database.init_database()
    await enqueue(database, queue)
    old_token = uuid4()
    old = await claim_for(queue)(claim_token=old_token)
    scheduled, _ = await schedule_llm_retry(
        old["id"],
        version(old),
        [Diagnostic("llm_timeout", "classification")],
        collection=queue == "collection",
    )
    assert scheduled
    assert await claim_for(queue)(claim_token=old_token) is None
    assert await claim_for(queue)(claim_token=uuid4()) is None
    assert len(await receipts(queue)) == 1
    await sql(
        f"UPDATE {TABLES[queue]} SET next_retry_at = NOW() - INTERVAL '1 second' WHERE id = %s",
        (old["id"],),
    )
    current = await claim_for(queue)(claim_token=uuid4())
    assert current["id"] == old["id"] and version(current) != version(old)
    assert await claim_for(queue)(claim_token=old_token) is None
    assert len(await receipts(queue)) == 2


@pytest.mark.parametrize("queue", QUEUES)
async def test_receipt_from_different_queue_is_rejected(database, queue):
    await database.init_database()
    await enqueue(database, queue)
    token = uuid4()
    await claim_for(queue)(claim_token=token)
    other_queue = QUEUES[(QUEUES.index(queue) + 1) % len(QUEUES)]
    await enqueue(database, other_queue)
    previous = await receipts(other_queue)
    with pytest.raises(ValueError):
        await claim_for(other_queue)(claim_token=token)
    assert await receipts(other_queue) == previous


async def test_schema_ten_migration_preserves_existing_queued_work(database):
    from app.db.schema import CURRENT_SCHEMA_VERSION
    from schema_helpers import restore_schema_ten

    await database.init_database()
    # Build collections first so its setup cannot consume the classification under test.
    items = {queue: await enqueue(database, queue) for queue in reversed(QUEUES)}
    snapshots = {queue: await persisted(queue, item) for queue, item in items.items()}
    await restore_schema_ten()
    await database.init_database()
    assert (await sql("SELECT MAX(version) AS value FROM schema_migrations"))[0]["value"] == (
        CURRENT_SCHEMA_VERSION
    )
    assert await sql("SELECT * FROM worker_claims") == []
    for queue, item in items.items():
        assert await persisted(queue, item) == snapshots[queue]
        assert (await claim_for(queue)(claim_token=uuid4()))["id"] == item["id"]
