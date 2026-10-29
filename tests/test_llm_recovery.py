"""Recovery policy and real PostgreSQL worker/vote transitions; no live providers."""

from __future__ import annotations

import asyncio
import io
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from app.api.searches import search_progress
from app.auth.security import APIPrincipal
from app.db.classification import votes as votes
from app.db.connection import _require_database_pool
from app.db.execution.retries import schedule_llm_retry
from app.policies.quotas import QuotaExceeded
from app.policies.retries import RetryPolicy, enforce_retry_date, plan_retry
from app.workers import classification as classification_worker
from app.workers import collection as collection_worker
from app.workers import stores as vote_store
from fastapi import Response
from helpers.classification import MODELS, PAGE
from helpers.classification import response as _response
from helpers.inspection import stored_candidate
from helpers.workflows import candidate_for, decision

from collector.diagnostics import Diagnostic, PersistenceFailure
from collector.storage.models import CollectionReport, CollectionResult

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "code,attempt,scheduled",
    [
        ("llm_timeout", 1, True),
        ("llm_timeout", 3, False),
        ("llm_network_error", 1, True),
        ("llm_rate_limited", 1, True),
        ("llm_unavailable", 1, True),
        ("llm_invalid_response", 1, True),
        ("llm_invalid_response", 2, False),
        ("llm_configuration_error", 1, False),
        ("llm_response_too_large", 1, False),
        ("processing_failed", 1, False),
        ("persistence_failed", 1, False),
    ],
)
def test_retry_policy(code, attempt, scheduled):
    due, diagnostics = plan_retry(
        [Diagnostic(code, "classification", attempt=attempt)],
        round_number=attempt - 1,
        started_at=NOW,
        now=NOW,
    )
    assert (due is not None) is scheduled
    if scheduled:
        assert NOW < due < NOW + timedelta(seconds=3)
        assert diagnostics[0].recovery == "automatic"


def test_retry_after_and_budget_are_not_shortened():
    due = NOW + timedelta(seconds=70)
    error = Diagnostic("llm_rate_limited", "classification", retry_at=due.isoformat())
    actual, _ = plan_retry([error], round_number=0, started_at=NOW, now=NOW)
    assert actual == due
    far = NOW + timedelta(hours=1)
    error = Diagnostic("llm_rate_limited", "classification", retry_at=far.isoformat())
    actual, errors = plan_retry([error], round_number=0, started_at=NOW, now=NOW)
    assert actual is None and errors[0].retry_at == far.isoformat()
    with pytest.raises(QuotaExceeded) as caught:
        enforce_retry_date([error.to_dict()], now=NOW)
    assert caught.value.retry_after_seconds == 3600
    assert (
        plan_retry(
            [Diagnostic("llm_timeout", "classification")],
            round_number=0,
            started_at=NOW - timedelta(seconds=121),
            now=NOW,
        )[0]
        is None
    )


@pytest.mark.parametrize(
    "setting,value",
    [
        ("LLM_MAX_ATTEMPTS", "0"),
        ("LLM_INVALID_MAX_ATTEMPTS", "4"),
        ("LLM_RETRY_WINDOW_SECONDS", "nan"),
    ],
)
def test_invalid_configuration(setting, value, monkeypatch):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        RetryPolicy.configured()


async def sql(query, params=None):
    async with _require_database_pool().connection() as connection:
        cursor = await connection.execute(query, params)
        return await cursor.fetchall() if cursor.description else []


async def setup_work(database, kind):
    candidate = await candidate_for(database)
    await database.complete_search_session(candidate["search_session_id"], "alice", origin="online")
    if kind == "repository":
        item = await stored_candidate(candidate["id"], "alice")
        item["owner_id"] = "alice"
        return candidate, item
    await database.complete_candidate_classification(candidate["id"], "alice", decision())
    return candidate, await database.claim_pending_collection_job()


async def execute(kind, item):
    worker = (
        classification_worker._run_classification
        if kind == "repository"
        else collection_worker._run_collection_job
    )
    with ThreadPoolExecutor(1) as executor:
        await worker(item, executor)


async def next_attempt(database, kind, item_id):
    table = "repository_candidates" if kind == "repository" else "collection_jobs"
    await sql(
        f"UPDATE {table} SET next_retry_at = NOW() - INTERVAL '1 second' WHERE id = %s", (item_id,)
    )
    return await (
        database.claim_candidate_classification()
        if kind == "repository"
        else database.claim_pending_collection_job()
    )


def install_collection(monkeypatch):
    def collect(url, *, classifier, **options):
        classifier.classify(PAGE, [])
        return CollectionResult(report=CollectionReport(verification_complete=True))

    monkeypatch.setattr(collection_worker, "collect_repository_candidate_with_report", collect)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["repository", "page"])
@pytest.mark.parametrize("failure", ["timeout", "invalid"])
async def test_automatic_retry_preserves_successes_and_survives_restart(
    database,
    transport,
    monkeypatch,
    kind,
    failure,
):
    await database.init_database()
    candidate, item = await setup_work(database, kind)
    install_collection(monkeypatch)
    calls = Counter()

    def request(req, timeout):
        model = json.loads(req.data)["model"]
        calls[model] += 1
        if model == MODELS[2] and calls[model] == 1:
            if failure == "timeout":
                raise TimeoutError()
            return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
        return _response(kind, model != MODELS[0])

    transport(request)
    await execute(kind, item)
    progress = await search_progress(
        candidate["search_session_id"], APIPrincipal("alice"), Response()
    )
    assert progress.execution_status == "waiting_retry" and progress.polling_required
    assert progress.outcome is None
    assert (
        await (
            database.claim_candidate_classification()
            if kind == "repository"
            else database.claim_pending_collection_job()
        )
        is None
    )
    table = "repository_candidates" if kind == "repository" else "collection_jobs"
    row = (await sql(f"SELECT * FROM {table} WHERE id = %s", (item["id"],)))[0]
    assert row["retry_round"] == 1
    await votes.mark_interrupted_votes_error()
    await database.mark_interrupted_candidate_classifications_error()
    await database.mark_interrupted_collection_jobs_error()
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    resumed = await next_attempt(database, kind, item["id"])
    await execute(kind, resumed)
    assert calls == {MODELS[0]: 1, MODELS[1]: 1, MODELS[2]: 2}
    row = (await sql(f"SELECT * FROM {table} WHERE id = %s", (item["id"],)))[0]
    assert row["classification_status" if kind == "repository" else "status"] == (
        "accepted" if kind == "repository" else "done"
    )
    assert row["retry_cycle"] is not None


@pytest.mark.anyio
@pytest.mark.parametrize("failure,max_calls", [("timeout", 3), ("invalid", 2), ("auth", 1)])
async def test_retry_exhaustion_is_terminal(database, transport, failure, max_calls):
    from urllib.error import HTTPError

    await database.init_database()
    candidate, item = await setup_work(database, "repository")
    calls = Counter()

    def request(req, timeout):
        model = json.loads(req.data)["model"]
        calls[model] += 1
        if model == MODELS[2]:
            if failure == "auth":
                raise HTTPError(req.full_url, 401, "secret", {}, None)
            if failure == "timeout":
                raise TimeoutError()
            return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
        return _response("repository", True)

    transport(request)
    for attempt in range(max_calls):
        if attempt:
            item = await next_attempt(database, "repository", candidate["id"])
        await execute("repository", item)
    row = await stored_candidate(candidate["id"], "alice")
    assert row["classification_status"] == "error"
    assert calls == {MODELS[0]: 1, MODELS[1]: 1, MODELS[2]: max_calls}
    assert await database.claim_candidate_classification() is None
    progress = await search_progress(
        candidate["search_session_id"], APIPrincipal("alice"), Response()
    )
    assert not progress.polling_required and progress.outcome == "incomplete"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation,after_commit",
    [
        ("prepare_vote_run", True),
        ("claim_vote", True),
        ("finish_vote", True),
        ("finish_vote", False),
    ],
)
async def test_transient_vote_persistence_never_recalls_model(
    database,
    monkeypatch,
    operation,
    after_commit,
):
    await database.init_database()
    candidate, item = await setup_work(database, "repository")
    original = getattr(vote_store, operation)
    saves = 0
    invokes = 0

    async def flaky(*args, **kwargs):
        nonlocal saves
        saves += 1
        if saves == 1:
            if after_commit:
                await original(*args, **kwargs)
            raise psycopg.OperationalError("connection lost")
        return await original(*args, **kwargs)

    monkeypatch.setattr(vote_store, operation, flaky)
    store = vote_store.PostgresVoteStore(
        asyncio.get_running_loop(),
        candidate_id=candidate["id"],
        expected_updated_at=datetime.fromisoformat(item["updated_at"]),
    )

    def invoke():
        nonlocal invokes
        invokes += 1
        return {"accepted": False}

    result = await asyncio.to_thread(
        store.run, {"configuration": [{"voter_id": "a"}], "payload": {}}, "a", invoke
    )
    assert result == {"accepted": False} and invokes == 1 and saves == 2
    vote = (await sql("SELECT * FROM classification_votes"))[0]
    assert vote["attempts"] == 1 and vote["status"] == "succeeded"


@pytest.mark.anyio
async def test_stale_worker_and_conflicting_vote_writes_are_rejected(database):
    await database.init_database()
    candidate, item = await setup_work(database, "repository")
    version = datetime.fromisoformat(item["updated_at"])
    scope = {"candidate_id": candidate["id"], "expected_updated_at": version}
    run = await votes.prepare_vote_run(
        {"configuration": [{"voter_id": "a"}], "payload": {}}, **scope
    )
    vote = await votes.claim_vote(run, "a", **scope)
    await votes.finish_vote(run, "a", vote["attempt_token"], response={"ok": True}, **scope)
    await votes.finish_vote(run, "a", vote["attempt_token"], response={"ok": True}, **scope)
    with pytest.raises(PersistenceFailure):
        await votes.finish_vote(run, "a", vote["attempt_token"], response={"ok": False}, **scope)
    await schedule_llm_retry(
        candidate["id"], version, [Diagnostic("llm_timeout", "classification")]
    )
    with pytest.raises(PersistenceFailure):
        await votes.claim_vote(run, "a", **scope)
    # Replay of scheduling after a lost acknowledgement does not add another round.
    await schedule_llm_retry(
        candidate["id"], version, [Diagnostic("llm_timeout", "classification")]
    )
    assert (await sql("SELECT retry_round FROM repository_candidates"))[0]["retry_round"] == 1


@pytest.mark.anyio
async def test_reinitialization_preserves_votes_and_retry_counters(database):
    from app.db.schema import CURRENT_SCHEMA_VERSION

    await database.init_database()
    candidate, item = await setup_work(database, "repository")
    run = await votes.prepare_vote_run(
        {"configuration": [{"voter_id": "a"}], "payload": {}}, candidate_id=candidate["id"]
    )
    vote = await votes.claim_vote(run, "a", candidate_id=candidate["id"])
    await votes.finish_vote(
        run, "a", vote["attempt_token"], response={"accepted": False}, candidate_id=candidate["id"]
    )
    previous = (await sql("SELECT * FROM classification_votes"))[0]
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    await database.init_database()
    saved = (await sql("SELECT * FROM classification_votes"))[0]
    assert saved["response"] == {"accepted": False} and saved["attempts"] == 1
    assert saved == previous
    assert (await sql("SELECT max(version) AS v FROM schema_migrations"))[0][
        "v"
    ] == CURRENT_SCHEMA_VERSION


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["repository", "page"])
async def test_expired_queued_retry_does_not_invoke_models(database, transport, monkeypatch, kind):
    await database.init_database()
    candidate, item = await setup_work(database, kind)
    install_collection(monkeypatch)
    calls = Counter()

    def request(req, timeout):
        model = json.loads(req.data)["model"]
        calls[model] += 1
        if model == MODELS[2]:
            raise TimeoutError()
        return _response(kind, True)

    transport(request)
    await execute(kind, item)
    table = "repository_candidates" if kind == "repository" else "collection_jobs"
    await sql(f"UPDATE {table} SET retry_started_at = NOW() - INTERVAL '10 minutes'")
    resumed = await next_attempt(database, kind, item["id"])
    await execute(kind, resumed)
    assert calls == dict.fromkeys(MODELS, 1)
    progress = await search_progress(
        candidate["search_session_id"], APIPrincipal("alice"), Response()
    )
    assert not progress.polling_required and progress.outcome == "incomplete"
    assert any(error.code == "llm_retry_exhausted" for error in progress.errors)


def test_mixed_permanent_and_transient_votes_do_not_schedule_retry():
    due, _ = plan_retry(
        [
            Diagnostic("llm_timeout", "classification"),
            Diagnostic(
                "llm_configuration_error", "classification", recovery="configuration_required"
            ),
        ],
        round_number=0,
        started_at=NOW,
        now=NOW,
    )
    assert due is None
