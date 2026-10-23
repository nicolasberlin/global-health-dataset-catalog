"""Exercise durable partial votes through real ensembles and PostgreSQL."""

from __future__ import annotations

import asyncio
import io
import json
import threading
from collections import Counter
from dataclasses import replace

import pytest
from app.db import classification_votes as votes
from app.db.connection import _fetchall, _require_database_pool
from app.vote_store import PostgresVoteStore
from helpers.classification import KEYS, MODELS, PAGE
from helpers.classification import response as _response
from helpers.workflows import candidate_for, rows, wait_until

from collector.classification import factory
from collector.classification.page import PageClassificationError
from collector.diagnostics import PersistenceFailure

pytestmark = pytest.mark.anyio


async def scope_for(database, kind):
    if kind == "repository":
        candidate = await candidate_for(database)
        return {"candidate_id": candidate["id"]}
    job = await database.create_collection_job(PAGE.url)
    await database.mark_collection_job_running(job["id"])
    return {"job_id": job["id"]}


def classify(kind, scope, loop, page=PAGE):
    store = PostgresVoteStore(loop, **scope)
    if kind == "page":
        return factory.build_default_page_classifier(vote_store=store).classify(page, [])
    return factory.build_default_repository_result_classifier(vote_store=store).classify(page)


@pytest.mark.parametrize("kind", ["repository", "page"])
@pytest.mark.parametrize("failure", ["timeout", "invalid_vote"])
async def test_retry_only_failed_model_preserves_negative_votes(
    database,
    transport,
    kind,
    failure,
):
    await database.init_database()
    scope = await scope_for(database, kind)
    calls = Counter()

    def request(req, timeout):
        model = json.loads(req.data)["model"]
        calls[model] += 1
        if model == MODELS[2] and calls[model] == 1:
            if failure == "timeout":
                raise TimeoutError("provider down")
            return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
        return _response(kind, model != MODELS[0])

    transport(request)
    loop = asyncio.get_running_loop()
    with pytest.raises(PageClassificationError, match="At least 3 classifier votes"):
        await asyncio.to_thread(classify, kind, scope, loop)
    saved = await rows("SELECT * FROM classification_votes ORDER BY voter_id")
    failed_history = (await rows(
        "SELECT * FROM classification_vote_attempts WHERE status = 'error'"
    ))[0]
    assert failed_history["voter_id"] == "epfl_rcp_apertus_meditron"
    assert failed_history["model"] == MODELS[2]
    assert failed_history["attempt"] == 1
    assert failed_history["started_at"] <= failed_history["finished_at"]
    assert failed_history["error"]
    assert Counter(v["status"] for v in saved) == {"succeeded": 2, "error": 1}
    assert next(v for v in saved if v["status"] == "error")["response"] is None
    table = "repository_candidates" if kind == "repository" else "collection_jobs"
    progress = (await rows(f"SELECT classification_progress FROM {table}"))[0]
    assert progress["classification_progress"] == {"total": 3, "succeeded": 2, "failed": 1}
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    result = await asyncio.to_thread(classify, kind, scope, loop)
    assert result.accepted
    assert calls == {MODELS[0]: 1, MODELS[1]: 1, MODELS[2]: 2}
    summary = result.ensemble if kind == "repository" else result.dataset_signals["ensemble"]
    assert summary["accepted_votes"] == 2
    assert summary["successful_votes"] == 3
    snapshot = json.dumps((await rows("SELECT snapshot FROM classification_runs"))[0]["snapshot"])
    assert all(key not in snapshot for key in KEYS)
    assert all(model in snapshot for model in MODELS)
    history = await rows("SELECT * FROM classification_vote_attempts ORDER BY attempt")
    assert len(history) == 4
    assert next(h for h in history if h["status"] == "error") == failed_history
    assert next(h for h in history if h["attempt"] == 2)["status"] == "succeeded"
    assert all(key not in json.dumps(history, default=str) for key in KEYS)
    if kind == "repository":
        exported = await votes.read_candidate_vote_history(scope["candidate_id"], "alice")
        assert len(exported["attempts"]) == 4
        failed = next(a for a in exported["attempts"] if a["status"] == "error")
        assert failed["errors"] and "error" not in failed
        assert await votes.read_candidate_vote_history(scope["candidate_id"], "bob") is None


async def test_fast_votes_are_saved_before_slowest_model_finishes(database, transport):
    await database.init_database()
    scope = await scope_for(database, "repository")
    release = threading.Event()

    def request(req, timeout):
        if json.loads(req.data)["model"] == MODELS[0]:
            assert release.wait(timeout=5)
        return _response("repository", True)

    transport(request)
    task = asyncio.create_task(
        asyncio.to_thread(
            classify,
            "repository",
            scope,
            asyncio.get_running_loop(),
        )
    )

    async def two_saved():
        return len(await rows("SELECT * FROM classification_votes WHERE status='succeeded'")) == 2

    try:
        await wait_until(two_saved)
        assert not task.done()
    finally:
        release.set()
        await task


@pytest.mark.parametrize("kind", ["repository", "page"])
async def test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup(
    database, kind,
):
    await database.init_database()
    scope = await scope_for(database, kind)
    table = "repository_candidates" if kind == "repository" else "collection_jobs"
    scope_id = scope.get("candidate_id", scope.get("job_id"))
    async with _require_database_pool().connection() as connection:
        current = (await _fetchall(
            connection, f"SELECT updated_at FROM {table} WHERE id = %s", (scope_id,),
        ))[0]
    scope["expected_updated_at"] = current["updated_at"]
    snapshot = {"configuration": [{"voter_id": "a"}, {"voter_id": "b"}], "payload": {}}
    run = await votes.prepare_vote_run(snapshot, **scope)
    old = await votes.claim_vote(run, "a", **scope)
    if kind == "repository":
        await database.mark_interrupted_candidate_classifications_error()
    else:
        await database.mark_interrupted_collection_jobs_error()
    with pytest.raises(PersistenceFailure, match="no longer running"):
        await votes.claim_vote(run, "b", **scope)
    with pytest.raises(PersistenceFailure, match="no longer running"):
        await votes.finish_vote(
            run, "a", old["attempt_token"], response={"accepted": True}, **scope,
        )
    await votes.mark_interrupted_votes_error()
    saved = await rows("SELECT status, response FROM classification_votes ORDER BY voter_id")
    assert saved == [{"status": "error", "response": None}, {"status": "pending", "response": None}]


@pytest.mark.parametrize("change", ["input", "model", "prompt"])
async def test_changed_inputs_or_configuration_start_fresh_run(
    database,
    transport,
    monkeypatch,
    change,
):
    await database.init_database()
    scope = await scope_for(database, "repository")
    calls = []

    def request(req, timeout):
        calls.append(json.loads(req.data))
        return _response("repository", True)

    transport(request)
    loop = asyncio.get_running_loop()
    await asyncio.to_thread(classify, "repository", scope, loop)
    if change == "model":
        monkeypatch.setenv("RCP_DEEPSEEK_MODEL", "new-model")
    elif change == "prompt":
        original = factory.epfl_rcp_repository_relevance_provider_config

        def changed_provider(**kwargs):
            provider = original(**kwargs)

            def builder(payload, model):
                body = provider.request_body_builder(payload, model)
                body["messages"][0]["content"] += " A changed rule."
                return body

            return replace(provider, request_body_builder=builder)

        monkeypatch.setattr(
            factory, "epfl_rcp_repository_relevance_provider_config", changed_provider
        )
    page = replace(PAGE, search_query="different query") if change == "input" else PAGE
    await asyncio.to_thread(classify, "repository", scope, loop, page)
    assert len(calls) == 6
    assert len(await rows("SELECT id FROM classification_runs")) == 2


async def test_new_internal_collection_job_inherits_partial_votes(database, transport):
    await database.init_database()
    scope = await scope_for(database, "page")
    loop = asyncio.get_running_loop()
    calls = Counter()

    def request(req, timeout):
        model = json.loads(req.data)["model"]
        calls[model] += 1
        if model == MODELS[2] and calls[model] == 1:
            raise TimeoutError()
        return _response("page", True)

    transport(request)
    with pytest.raises(PageClassificationError):
        await asyncio.to_thread(classify, "page", scope, loop)
    await database.mark_collection_job_error(scope["job_id"], "Model unavailable")
    new = await database.create_collection_job(PAGE.url)
    await database.mark_collection_job_running(new["id"])
    result = await asyncio.to_thread(classify, "page", {"job_id": new["id"]}, loop)
    assert result.accepted
    assert calls == {MODELS[0]: 1, MODELS[1]: 1, MODELS[2]: 2}
    assert len(await rows("SELECT id FROM classification_runs")) == 1
    assert (await database.get_collection_job(new["id"]))["classification_progress"] == {
        "total": 3,
        "succeeded": 3,
        "failed": 0,
    }
