"""Search worker instances keep dependencies stable and attempt state isolated."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from threading import get_ident
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.policies.quotas import QuotaExceeded, QuotaUnavailable
from app.workers.search import worker as module
from app.workers.search.worker import SearchWorker
from app.workers.sql_retries import persist_with_retry
from psycopg.errors import DiskFull

from collector.execution import ExecutionControl, execution_control
from collector.repository_search import RepositorySearchResponse
from collector.storage.models import CollectedDataset

pytestmark = pytest.mark.anyio


def job(query="malaria"):
    return {
        "id": uuid4(),
        "owner_id": "alice",
        "query": query,
        "client_key": None,
        "attempt_token": uuid4(),
        "attempt_number": 1,
    }


def dataset():
    return CollectedDataset(
        dataset_url="https://example.org/data",
        title="Malaria",
        description="",
        publisher="",
        hosting_platform="",
        uploader="",
        dataset_signals={},
        database_id=1,
    )


async def persist(operation, *, retry_storage_failures=False, retry_unexpected=False):
    return await operation()


async def test_claim_and_recover_delegate_with_the_original_attempt(monkeypatch):
    worker = SearchWorker(persist=persist)
    item = job()
    token = uuid4()
    claim = AsyncMock(return_value=item)
    fail = AsyncMock(return_value={"id": item["id"]})
    monkeypatch.setattr(module, "claim_search", claim)
    monkeypatch.setattr(module, "fail_discovery", fail)

    assert worker.name == "search"
    assert await worker.claim(claim_token=token) is item
    claim.assert_awaited_once_with(claim_token=token)
    assert await worker.recover(item) == {"id": item["id"]}
    assert fail.await_args.args == (item,)
    assert fail.await_args.kwargs["origin"] == "database"
    assert fail.await_args.kwargs["diagnostics"][0]["code"] == "persistence_failed"


async def test_default_dependencies_are_resolved_at_construction(monkeypatch):
    lookup = AsyncMock(return_value=[dataset()])
    provider = Mock()
    persistence = AsyncMock(side_effect=persist)
    complete = AsyncMock()
    monkeypatch.setattr(module, "lookup_local", lookup)
    monkeypatch.setattr(module, "search_repository_metadata", provider)
    monkeypatch.setattr(module, "persist_with_retry", persistence)
    worker = SearchWorker()
    replacement = AsyncMock(side_effect=AssertionError("Dependency changed after construction"))
    monkeypatch.setattr(module, "lookup_local", replacement)
    monkeypatch.setattr(module, "persist_with_retry", replacement)
    monkeypatch.setattr(module, "complete_discovery", complete)

    with ThreadPoolExecutor(1) as executor:
        await worker.execute(job(), executor)

    lookup.assert_awaited_once_with("malaria")
    replacement.assert_not_called()
    provider.assert_not_called()
    complete.assert_awaited_once()
    assert complete.await_args.args[1].origin == "database"
    assert persistence.await_args.kwargs == {"retry_storage_failures": True}


async def test_one_instance_keeps_failure_origin_local_to_each_execution(monkeypatch):
    online_started = asyncio.Event()

    async def lookup(query):
        if query == "local":
            await online_started.wait()
            raise RuntimeError("local lookup failed")
        return []

    async def reserve(item):
        online_started.set()
        return True

    fail = AsyncMock()
    worker = SearchWorker(
        local_lookup=lookup,
        provider=Mock(side_effect=RuntimeError("provider failed")),
        persist=persist,
    )
    monkeypatch.setattr(module, "reserve_external_search", reserve)
    monkeypatch.setattr(module, "fail_discovery", fail)

    with ThreadPoolExecutor(2) as executor:
        await asyncio.wait_for(
            asyncio.gather(
                worker.execute(job("local"), executor),
                worker.execute(job("online"), executor),
            ),
            timeout=1,
        )

    origins = {call.args[0]["query"]: call.kwargs["origin"] for call in fail.await_args_list}
    assert origins == {"local": "database", "online": "online"}


async def test_provider_runs_with_execution_context_and_completed_online_outcome(monkeypatch):
    control = ExecutionControl()
    main_thread = get_ident()

    def provider(query):
        assert query == "malaria"
        assert execution_control.get() is control
        assert get_ident() != main_thread
        return RepositorySearchResponse()

    worker = SearchWorker(
        local_lookup=AsyncMock(return_value=[]),
        provider=provider,
        persist=persist,
    )
    complete = AsyncMock()
    monkeypatch.setattr(module, "reserve_external_search", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "complete_discovery", complete)
    token = execution_control.set(control)
    try:
        with ThreadPoolExecutor(1) as executor:
            await worker.execute(job(), executor)
    finally:
        execution_control.reset(token)

    assert complete.await_args.args[1].origin == "online"
    assert complete.await_args.args[1].complete


@pytest.mark.parametrize("failure", [QuotaExceeded(12), QuotaUnavailable("quota offline")])
async def test_quota_diagnostics_take_precedence_during_publication(monkeypatch, failure):
    worker = SearchWorker(local_lookup=AsyncMock(return_value=[dataset()]), persist=persist)
    fail = AsyncMock()
    monkeypatch.setattr(module, "complete_discovery", AsyncMock(side_effect=failure))
    monkeypatch.setattr(module, "fail_discovery", fail)
    before = datetime.now(timezone.utc)

    with ThreadPoolExecutor(1) as executor:
        await worker.execute(job(), executor)

    options = fail.await_args.kwargs
    code = options["diagnostics"][0]["code"]
    if isinstance(failure, QuotaExceeded):
        assert code == "api_quota_exceeded"
        assert (options["retry_at"] - before).total_seconds() >= 12
    else:
        assert code == "quota_service_unavailable" and options["retry_at"] is None


async def test_repairable_storage_failure_reuses_the_computed_result(monkeypatch):
    lookup = AsyncMock(return_value=[dataset()])
    complete = AsyncMock(side_effect=[DiskFull("full"), True])
    fail = AsyncMock()
    worker = SearchWorker(
        local_lookup=lookup,
        persist=partial(persist_with_retry, initial_delay=0),
    )
    monkeypatch.setattr(module, "complete_discovery", complete)
    monkeypatch.setattr(module, "fail_discovery", fail)

    with ThreadPoolExecutor(1) as executor:
        await worker.execute(job(), executor)

    lookup.assert_awaited_once()
    assert complete.await_count == 2
    assert complete.await_args_list[0].args[1] is complete.await_args_list[1].args[1]
    fail.assert_not_awaited()
