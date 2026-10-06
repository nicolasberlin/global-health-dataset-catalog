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
from app import classification_worker, collection_worker, vote_store
from app.db import classification_votes as votes
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.connection import _require_database_pool
from app.db.task_retries import schedule_llm_retry
from app.quota_policy import QuotaExceeded
from app.retry_policy import RetryPolicy, enforce_retry_date, plan_retry
from app.routes.collector import search_progress
from app.security import APIPrincipal
from fastapi import Response
from schema_helpers import restore_schema_eight
from test_classifier_factory import MODELS, PAGE, _response
from test_collection_workflow import candidate_for, decision
from test_vote_persistence import transport  # noqa: F401 - provider fixture

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
        item = await database.get_repository_candidate(candidate["id"], "alice")
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
    def collect(url, *, classifier):
        classifier.classify(PAGE, [])
        return CollectionResult(report=CollectionReport(verification_complete=True))

    monkeypatch.setattr(collection_worker, "collect_repository_candidate_with_report", collect)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["repository", "page"])
@pytest.mark.parametrize("failure", ["timeout", "invalid"])
async def test_automatic_retry_preserves_successes_and_survives_restart(
    database,
    transport,  # noqa: F811
    monkeypatch,
    kind,
    failure,  # noqa: F811
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
async def test_retry_exhaustion_is_terminal(database, transport, failure, max_calls):  # noqa: F811
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
    row = await database.get_repository_candidate(candidate["id"], "alice")
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
async def test_incomplete_collection_recovery_is_owned_idempotent_and_preserves_results(database):
    from test_database import _mortality_dataset

    await database.init_database()
    candidate, job = await setup_work(database, "page")
    result = CollectionResult(
        datasets=[_mortality_dataset()],
        report=CollectionReport(
            errors=[Diagnostic("verification_unconfirmed", "validation")],
            verification_complete=False,
        ),
    )
    await database.complete_collection_job(job["id"], result)
    ids = await sql("SELECT dataset_id FROM dataset_discovery_observations")
    assert await retry_collection_job_for_owner(job["id"], "bob") is None
    await asyncio.gather(
        *[
            retry_collection_job_for_owner(job["id"], "alice", idempotency_key="retry")
            for _ in range(2)
        ]
    )
    retried = await database.claim_pending_collection_job()
    assert retried["id"] == job["id"]
    await database.complete_collection_job(job["id"], CollectionResult(report=result.report))
    assert (await database.get_collection_job(job["id"]))["saved_count"] == 1
    await retry_collection_job_for_owner(job["id"], "alice", idempotency_key="retry")
    assert await database.claim_pending_collection_job() is None
    assert await sql("SELECT dataset_id FROM dataset_discovery_observations") == ids


@pytest.mark.anyio
async def test_migration_eight_preserves_votes(database):
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
    await restore_schema_eight()
    await database.init_database()
    await database.init_database()
    saved = (await sql("SELECT * FROM classification_votes"))[0]
    assert saved["response"] == {"accepted": False} and saved["attempts"] == 1
    assert saved["cycle_attempts"] == 0
    assert (await sql("SELECT max(version) AS v FROM schema_migrations"))[0][
        "v"
    ] == CURRENT_SCHEMA_VERSION


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["repository", "page"])
async def test_manual_cycle_reclaims_unsaved_vote_and_fences_old_worker(database, kind):
    await database.init_database()
    candidate, item = await setup_work(database, kind)
    key = "candidate_id" if kind == "repository" else "job_id"
    old_scope = {key: item["id"], "expected_updated_at": datetime.fromisoformat(item["updated_at"])}
    snapshot = {"configuration": [{"voter_id": "a"}], "payload": {}}
    run = await votes.prepare_vote_run(snapshot, **old_scope)
    old_vote = await votes.claim_vote(run, "a", **old_scope)
    # Simulate permanent persistence failure after the provider returned.
    if kind == "repository":
        await database.fail_candidate_classification(candidate["id"], "alice", "save failed")
        await database.enqueue_candidate_classification(candidate["id"], "alice", retry=True)
        resumed = await database.claim_candidate_classification()
    else:
        await database.mark_collection_job_error(item["id"], "save failed")
        await retry_collection_job_for_owner(item["id"], "alice")
        resumed = await database.claim_pending_collection_job()
    new_scope = {
        key: item["id"],
        "expected_updated_at": datetime.fromisoformat(resumed["updated_at"]),
    }
    assert await votes.prepare_vote_run(snapshot, **new_scope) == run
    new_vote = await votes.claim_vote(run, "a", **new_scope)
    assert new_vote["cycle_attempts"] == 1 and new_vote["attempts"] == 2
    with pytest.raises(PersistenceFailure):
        await votes.finish_vote(
            run, "a", old_vote["attempt_token"], response={"ok": True}, **old_scope
        )
    with pytest.raises(PersistenceFailure):
        await votes.finish_vote(
            run, "a", old_vote["attempt_token"], response={"ok": True}, **new_scope
        )
    await votes.finish_vote(run, "a", new_vote["attempt_token"], response={"ok": True}, **new_scope)


@pytest.mark.anyio
async def test_provider_deadline_blocks_vote_even_in_new_manual_cycle(database):
    from collector.classification.page import PageClassificationError

    await database.init_database()
    candidate, item = await setup_work(database, "repository")
    scope = {
        "candidate_id": item["id"],
        "expected_updated_at": datetime.fromisoformat(item["updated_at"]),
    }
    run = await votes.prepare_vote_run({"configuration": [{"voter_id": "a"}]}, **scope)
    vote = await votes.claim_vote(run, "a", **scope)
    diagnostic = Diagnostic(
        "llm_rate_limited",
        "classification",
        retry_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    await votes.finish_vote(run, "a", vote["attempt_token"], errors=[diagnostic.to_dict()], **scope)
    # Parent diagnostics missing after interruption must not bypass the stored vote deadline.
    await database.fail_candidate_classification(candidate["id"], "alice", "interrupted")
    await database.enqueue_candidate_classification(candidate["id"], "alice", retry=True)
    item = await database.claim_candidate_classification()
    scope["expected_updated_at"] = datetime.fromisoformat(item["updated_at"])
    with pytest.raises(PageClassificationError) as error:
        await votes.claim_vote(run, "a", **scope)
    assert error.value.diagnostics[0].retry_at == diagnostic.retry_at
    assert (await sql("SELECT attempts FROM classification_votes"))[0]["attempts"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["repository", "page"])
async def test_manual_http_retry_honors_provider_deadline_and_owner(database, monkeypatch, kind):
    from app.main import app
    from app.security import require_api_principal
    from httpx import ASGITransport, AsyncClient

    await database.init_database()
    candidate, item = await setup_work(database, kind)
    diagnostic = Diagnostic(
        "llm_rate_limited",
        "classification",
        retry_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    errors = [diagnostic.to_dict()]
    if kind == "repository":
        await database.fail_candidate_classification(item["id"], "alice", "limited", errors=errors)
        url = f"/collector/repository-candidates/{item['id']}/classify?retry=true"
    else:
        await database.mark_collection_job_error(item["id"], "limited", errors=errors)
        url = f"/collector/collection-jobs/{item['id']}/retry"
    principal = APIPrincipal("bob")
    monkeypatch.setitem(app.dependency_overrides, require_api_principal, lambda: principal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(url, headers={"Idempotency-Key": "blocked"})).status_code == 404
        principal = APIPrincipal("alice")
        response = await client.post(url, headers={"Idempotency-Key": "blocked"})
        assert response.status_code == 429
        assert 3500 <= int(response.headers["Retry-After"]) <= 3600
    assert await sql("SELECT * FROM api_commands") == []
    assert await sql("SELECT * FROM api_rate_limits") == []


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["repository", "page"])
async def test_expired_queued_retry_does_not_invoke_models(database, transport, monkeypatch, kind):  # noqa: F811
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
