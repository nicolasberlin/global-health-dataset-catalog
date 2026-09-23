"""Exercise durable partial votes through real ensembles and PostgreSQL."""

from __future__ import annotations

import asyncio
import io
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial

import pytest
from app import classification_worker, collection_worker
from app.db import classification_votes as votes
from app.db.collection_jobs import retry_collection_job_for_owner
from app.db.connection import _fetchall, _require_database_pool
from app.vote_store import PostgresVoteStore
from test_classifier_factory import KEY_VARIABLES, KEYS, MODELS, PAGE, _response
from test_collection_workflow import candidate_for, decision, wait_until

from collector.classification import factory
from collector.classification.llm_client import HTTPJSONLLMClient
from collector.classification.page import PageClassificationError
from collector.storage.models import CollectionResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def transport(monkeypatch):
    for name, key in zip(KEY_VARIABLES, KEYS):
        monkeypatch.setenv(name, key)
    for _, variable, _, _ in factory._DEFAULT_VOTERS:
        monkeypatch.delenv(variable, raising=False)

    def install(request):
        monkeypatch.setattr(
            factory, "HTTPJSONLLMClient", partial(HTTPJSONLLMClient, request=request)
        )

    return install


async def rows(query):
    async with _require_database_pool().connection() as connection:
        return await _fetchall(connection, query)


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


async def test_restart_and_attempt_tokens_preserve_successes(database):
    await database.init_database()
    scope = await scope_for(database, "page")
    snapshot = {"configuration": [{"voter_id": "a"}, {"voter_id": "b"}], "payload": {}}
    run = await votes.prepare_vote_run(snapshot, **scope)
    first = await votes.claim_vote(run, "a", **scope)
    await votes.finish_vote(run, "a", first["attempt_token"], response={"accepted": False}, **scope)
    old = await votes.claim_vote(run, "b", **scope)
    with pytest.raises(PageClassificationError, match="already running"):
        await votes.claim_vote(run, "b", **scope)
    await votes.mark_interrupted_votes_error()
    await database.mark_interrupted_collection_jobs_error()
    assert (await votes.claim_vote(run, "a", **scope))["response"] == {"accepted": False}
    new = await votes.claim_vote(run, "b", **scope)
    with pytest.raises(PageClassificationError, match="no longer current"):
        await votes.finish_vote(
            run, "b", old["attempt_token"], response={"accepted": True}, **scope
        )
    await votes.finish_vote(run, "b", new["attempt_token"], response={"accepted": True}, **scope)
    assert new["attempts"] == 2


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


async def test_finalization_retry_reuses_all_votes(database, transport, monkeypatch):
    await database.init_database()
    candidate = await candidate_for(database)
    candidate["owner_id"] = "alice"
    calls = []

    def request(req, timeout):
        calls.append(req)
        return _response("repository", True)

    transport(request)
    original = classification_worker.complete_candidate_classification

    async def fail(*args):
        raise RuntimeError("temporary finalization failure")

    monkeypatch.setattr(classification_worker, "complete_candidate_classification", fail)
    with ThreadPoolExecutor(1) as executor:
        await classification_worker._run_classification(candidate, executor)
        failed = await database.get_repository_candidate(candidate["id"], "alice")
        assert failed["classification_status"] == "error"
        assert failed["classification_progress"]["succeeded"] == 3
        await database.enqueue_candidate_classification(candidate["id"], "alice", retry=True)
        claimed = await database.claim_candidate_classification()
        monkeypatch.setattr(classification_worker, "complete_candidate_classification", original)
        await classification_worker._run_classification(claimed, executor)
    assert len(calls) == 3
    assert (await database.get_repository_candidate(candidate["id"], "alice"))[
        "classification_status"
    ] == "accepted"
    assert len(await rows("SELECT id FROM collection_jobs")) == 1


async def test_collection_retry_is_owned_idempotent_and_reuses_votes(
    database,
    transport,
    monkeypatch,
):
    await database.init_database()
    candidate = await candidate_for(database)
    completion = await database.complete_candidate_classification(
        candidate["id"], "alice", decision()
    )
    job_id = completion.collection.job["id"]
    calls = Counter()

    def request(req, timeout):
        model = json.loads(req.data)["model"]
        calls[model] += 1
        if model == MODELS[2] and calls[model] == 1:
            raise TimeoutError()
        return _response("page", True)

    def collect(url, *, classifier):
        assert classifier.classify(PAGE, []).accepted
        return CollectionResult()

    transport(request)
    monkeypatch.setattr(collection_worker, "collect_repository_candidate_with_report", collect)
    with ThreadPoolExecutor(1) as executor:
        await collection_worker._run_collection_job(
            await database.claim_pending_collection_job(), executor
        )
        assert (await database.get_collection_job(job_id))["status"] == "error"
        assert await retry_collection_job_for_owner(job_id, "bob") is None
        retried = await asyncio.gather(
            *[retry_collection_job_for_owner(job_id, "alice") for _ in range(2)]
        )
        assert all(job["status"] == "pending" for job in retried)
        await collection_worker._run_collection_job(
            await database.claim_pending_collection_job(), executor
        )
    assert calls == {MODELS[0]: 1, MODELS[1]: 1, MODELS[2]: 2}
    assert (await database.get_collection_job(job_id))["status"] == "done"
    with pytest.raises(ValueError, match="Only a failed"):
        await retry_collection_job_for_owner(job_id, "alice")


async def test_collection_retry_route_enforces_owner_and_quota(database, monkeypatch):
    from app.routes.collector import retry_collection_job
    from app.security import APIPrincipal
    from fastapi import HTTPException

    await database.init_database()
    candidate = await candidate_for(database)
    completed = await database.complete_candidate_classification(
        candidate["id"],
        "alice",
        decision(),
    )
    job_id = completed.collection.job["id"]
    await database.mark_collection_job_running(job_id)
    await database.mark_collection_job_error(job_id, "private provider detail")
    charged = []

    async def quota(principal, operation):
        charged.append((principal.owner_id, operation))
        raise HTTPException(status_code=429, detail="Quota reached.")

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", quota)
    with pytest.raises(HTTPException) as unknown:
        await retry_collection_job(job_id, APIPrincipal("bob"))
    assert unknown.value.status_code == 404
    assert not charged
    with pytest.raises(HTTPException) as denied:
        await retry_collection_job(job_id, APIPrincipal("alice"))
    assert denied.value.status_code == 429
    assert (await database.get_collection_job(job_id))["status"] == "error"

    async def allow(principal, operation):
        charged.append((principal.owner_id, operation))

    monkeypatch.setattr("app.routes.collector.enforce_api_quota", allow)
    response = await retry_collection_job(job_id, APIPrincipal("alice"))
    assert response.job.status == "pending"
    assert "private provider detail" not in response.model_dump_json()
    assert "classification_progress" in response.model_dump_json()
    await retry_collection_job(job_id, APIPrincipal("alice"))
    assert charged == [("alice", "repository_classification")] * 2


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
