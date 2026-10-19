"""Regression coverage for public history, retention and baseline schema indexes."""

import pytest
from app.db.classification_votes import (
    claim_vote,
    finish_vote,
    prepare_vote_run,
    read_collection_vote_history,
)
from app.db.collection_traces import read_collection_trace, write_collection_trace
from app.db.connection import _require_database_pool
from app.db.maintenance import RetentionPolicy, maintain_database
from app.db.public_history import HistoryPage, PublicVoteAttempt
from app.db.schema import CURRENT_SCHEMA_VERSION, validate_database_schema
from helpers.workflows import candidate_for, claimed, decision, observation

pytestmark = pytest.mark.anyio


async def sql(statement, parameters=None):
    async with _require_database_pool().connection() as connection:
        cursor = await connection.execute(statement, parameters)
        return [dict(row) for row in await cursor.fetchall()] if cursor.description else []


def test_public_attempt_rebuilds_unsafe_legacy_values():
    attempt = PublicVoteAttempt.from_row(
        {
            "run_id": "not-a-uuid",
            "voter_id": {"secret": "PRIVATE"},
            "attempt": True,
            "retry_cycle": "PRIVATE",
            "model": "https://user:PRIVATE@provider.test/path",
            "status": {"secret": "PRIVATE"},
            "error": "Bearer PRIVATE",
            "errors": [
                {
                    "code": "PRIVATE",
                    "stage": [],
                    "message": "PRIVATE",
                    "recovery": {"secret": "PRIVATE"},
                    "retry_at": "PRIVATE",
                    "voter_id": "PRIVATE\n",
                }
            ],
            "evidence": "PRIVATE",
            "started_at": "PRIVATE",
            "finished_at": None,
        }
    ).to_dict()
    assert "PRIVATE" not in str(attempt)
    assert "error" not in attempt
    assert attempt["errors"][0]["code"] == "processing_failed"
    assert attempt["status"] == "error" and attempt["model"] == ""


@pytest.mark.parametrize("limit,offset", [(0, 0), (201, 0), (True, 0), (1, -1), (1, 10001)])
def test_history_page_rejects_unbounded_values(limit, offset):
    with pytest.raises(ValueError):
        HistoryPage(limit, offset)


async def test_trace_pages_and_vote_history_do_not_export_raw_provider_errors(database):
    job, version = await claimed(database)
    for sequence in range(5):
        assert await write_collection_trace(job["id"], version, sequence, observation())
    first = await read_collection_trace(job["id"], "alice", limit=2)
    second = await read_collection_trace(job["id"], "alice", limit=2, offset=first["next_offset"])
    assert [row["sequence"] for row in first["method_attempts"]] == [3, 4]
    assert [row["sequence"] for row in second["method_attempts"]] == [1, 2]
    assert first["history_truncated"] and second["next_offset"] == 4
    assert all(len(row["checks"]) == 1 for row in first["method_attempts"])
    assert await read_collection_trace(job["id"], "bob", limit=2) is None
    scope = {"job_id": job["id"], "expected_updated_at": version}
    run = await prepare_vote_run(
        {"configuration": [{"voter_id": "a", "body": {"model": "test-model"}}]}, **scope
    )
    vote = await claim_vote(run, "a", **scope)
    await finish_vote(
        run,
        "a",
        vote["attempt_token"],
        error="Bearer PRIVATE",
        errors=[
            {
                "code": "llm_timeout",
                "stage": "classification",
                "message": "Bearer PRIVATE",
                "recovery": "manual",
                "retry_at": "PRIVATE",
                "voter_id": "https://PRIVATE.test",
            }
        ],
        **scope,
    )
    exported = await read_collection_vote_history(job["id"], "alice", limit=1)
    attempt = exported["attempts"][0]
    assert "PRIVATE" not in str(exported) and "error" not in attempt
    assert attempt["errors"][0]["code"] == "llm_timeout"
    assert attempt["model"] == "test-model"
    assert (await sql("SELECT error FROM classification_vote_attempts WHERE run_id = %s", (run,)))[
        0
    ]["error"] == "Bearer PRIVATE"


async def test_legacy_trace_fields_are_filtered_again_on_read(database):
    job, version = await claimed(database)
    await write_collection_trace(job["id"], version, 0, observation())
    await sql(
        """UPDATE collection_method_attempts SET observation = '{
        "method":"browser","status":"succeeded","code":"PRIVATE","reason":"PRIVATE",
        "http_status":"PRIVATE","started_at":"PRIVATE","html":"PRIVATE",
        "requested_url":"https://user:PRIVATE@example.org/data?token=PRIVATE",
        "final_url":"http://example.org:broken/PRIVATE"}'::jsonb WHERE job_id = %s""",
        (job["id"],),
    )
    await sql("""UPDATE collection_resource_checks SET observation = '{
        "status":"PRIVATE","format":{"secret":"PRIVATE"},"error":"PRIVATE",
        "url":"https://user:PRIVATE@example.org/file?token=PRIVATE"}'::jsonb""")
    await sql(
        """UPDATE collection_jobs SET collection_coverage =
            '{"checked":1,"secret":"PRIVATE"}'::jsonb WHERE id=%s""",
        (job["id"],),
    )
    trace = await read_collection_trace(job["id"], "alice")
    assert "PRIVATE" not in str(trace)
    assert trace["coverage"] == {"checked": 1}


async def test_baseline_indexes_and_running_jobs_survive_reinitialization(database):
    job, _ = await claimed(database)
    await database.init_database()
    assert (await database.get_collection_job(job["id"]))["status"] == "running"
    rows = await sql("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
    assert {
        "dataset_discovery_observations_source_idx",
        "collection_job_candidates_candidate_latest_idx",
        "collection_method_claim_page_idx",
    } <= {row["indexname"] for row in rows}
    assert (await sql("SELECT max(version) AS version FROM schema_migrations"))[0][
        "version"
    ] == CURRENT_SCHEMA_VERSION


async def test_schema_validation_does_not_create_or_migrate_tables(database):
    with pytest.raises(RuntimeError, match="explicit migration"):
        await validate_database_schema()
    assert await sql("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()") == []
    await database.init_database()
    await validate_database_schema()


async def test_reused_job_reservation_preserves_saved_coverage_fields(database):
    job, _ = await claimed(database)
    await sql("""UPDATE collection_jobs SET collection_coverage = '{"checked":1}'::jsonb,
        collection_method_summary = '[{"method":"html","status":"running"}]'::jsonb
        WHERE id = %s""", (job["id"],))
    candidate = await candidate_for(database, "bob")
    completion = await database.complete_candidate_classification(
        candidate["id"], "bob", decision()
    )
    assert not completion.collection.created
    assert completion.collection.job["id"] == job["id"]
    assert completion.collection.job["coverage"] == {"checked": 1}
    assert completion.collection.job["method_attempts"] == [{"method": "html", "status": "running"}]


def test_command_retention_requires_explicit_replay_window():
    with pytest.raises(ValueError, match="explicit idempotency window"):
        RetentionPolicy(command_days=30)
    with pytest.raises(ValueError, match="explicit idempotency window"):
        RetentionPolicy(command_days=7, idempotency_window_days=30)
    assert RetentionPolicy().command_days is None
    assert RetentionPolicy().worker_claim_days is None


async def test_maintenance_dry_run_preserves_receipts_and_protects_active_history(database):
    job, version = await claimed(database)
    await write_collection_trace(job["id"], version, 0, observation())
    await sql("UPDATE collection_method_attempts SET created_at=NOW()-INTERVAL '120 days'")
    await sql("""INSERT INTO api_rate_limits
        (owner_id,operation,window_started_at,request_count,updated_at)
        VALUES ('old-owner','session',NOW()-INTERVAL '20 days',1,NOW()-INTERVAL '20 days')""")
    await sql(
        """INSERT INTO api_commands(owner_id,command_key,operation,fingerprint,result,created_at)
        VALUES ('alice','old-receipt','collection_retry','fingerprint',
            jsonb_build_object('job_id',%s),
            NOW()-INTERVAL '120 days')""",
        (job["id"],),
    )
    await sql("UPDATE worker_claims SET claim_version=NOW()-INTERVAL '120 days'")
    report = await maintain_database()
    assert report["dry_run"] and report["tables"]["quota_counters"]["eligible"] == 1
    assert report["tables"]["collection_traces"]["eligible"] == 0
    assert report["tables"]["command_receipts"]["retention_days"] is None
    assert report["tables"]["worker_receipts"]["retention_days"] is None
    assert len(await sql("SELECT * FROM api_rate_limits")) == 1
    assert len(await sql("SELECT * FROM collection_method_attempts")) == 1
    assert len(await sql("SELECT * FROM api_commands")) == 1
    policy = RetentionPolicy(command_days=90, worker_claim_days=90, idempotency_window_days=30)
    report = await maintain_database(policy)
    assert report["tables"]["command_receipts"]["eligible"] == 0
    assert report["tables"]["worker_receipts"]["eligible"] == 0
    await database.mark_collection_job_error(job["id"], "old failure")
    report = await maintain_database(policy)
    assert report["tables"]["collection_traces"]["eligible"] == 1
    assert report["tables"]["command_receipts"]["eligible"] == 1
    assert report["tables"]["worker_receipts"]["eligible"] == 2


async def test_maintenance_apply_only_deletes_selected_terminal_history(database):
    job, version = await claimed(database)
    await write_collection_trace(job["id"], version, 0, observation())
    await sql("UPDATE collection_method_attempts SET created_at=NOW()-INTERVAL '120 days'")
    await database.mark_collection_job_error(job["id"], "old failure")
    report = await maintain_database(apply=True)
    assert not report["dry_run"] and report["tables"]["collection_traces"]["deleted"] == 1
    assert await sql("SELECT * FROM collection_resource_checks") == []
    assert (await database.get_collection_job(job["id"]))["status"] == "error"
    assert len(await sql("SELECT * FROM worker_claims")) == 2


async def test_maintenance_keeps_replay_targets_and_respects_explicit_window(database):
    await database.init_database()
    old = await database.create_search_session("old search", "alice")
    recent_receipt = await database.create_search_session("still replayable", "alice")
    active = await database.create_search_session("queued work", "alice")
    for search in (old, recent_receipt):
        await database.complete_search_session(search["id"], "alice", origin="database")
    await sql("UPDATE search_sessions SET updated_at=NOW()-INTERVAL '120 days'")
    for key, search_id, days in (
        ("old-key", old["id"], 120),
        ("recent-key", recent_receipt["id"], 2),
        ("active-key", active["id"], 120),
    ):
        await sql(
            """INSERT INTO api_commands
            (owner_id,command_key,operation,fingerprint,result,created_at)
            VALUES ('alice',%s,'search_create','fingerprint',
                jsonb_build_object('search_id',%s::text),
                NOW()-%s*INTERVAL '1 day')""",
            (key, search_id, days),
        )
    policy = RetentionPolicy(search_days=90, command_days=45, idempotency_window_days=30)
    report = await maintain_database(policy, apply=True)
    assert report["tables"]["command_receipts"]["deleted"] == 1
    assert report["tables"]["search_history"]["deleted"] == 1
    assert {row["command_key"] for row in await sql("SELECT command_key FROM api_commands")} == {
        "recent-key",
        "active-key",
    }
    assert {row["id"] for row in await sql("SELECT id FROM search_sessions")} == {
        recent_receipt["id"],
        active["id"],
    }


async def test_maintenance_apply_refuses_live_api_ownership(database):
    from app.db.application_lock import ApplicationAlreadyRunning, application_lock

    await database.init_database()
    async with application_lock():
        with pytest.raises(ApplicationAlreadyRunning):
            await maintain_database(apply=True)


async def test_vote_history_retention_preserves_current_vote_cache(database):
    job, version = await claimed(database)
    scope = {"job_id": job["id"], "expected_updated_at": version}
    run = await prepare_vote_run({"configuration": [{"voter_id": "a"}]}, **scope)
    vote = await claim_vote(run, "a", **scope)
    await finish_vote(run, "a", vote["attempt_token"], response={"accepted": True}, **scope)
    await sql("UPDATE classification_vote_attempts SET finished_at=NOW()-INTERVAL '120 days'")
    report = await maintain_database(apply=True)
    assert report["tables"]["vote_history"]["deleted"] == 0  # Parent still running.
    await database.mark_collection_job_error(job["id"], "old failure")
    report = await maintain_database(apply=True)
    assert report["tables"]["vote_history"]["deleted"] == 1
    assert await sql("SELECT * FROM classification_vote_attempts") == []
    assert len(await sql("SELECT * FROM classification_runs")) == 1
    assert (await sql("SELECT response FROM classification_votes"))[0]["response"] == {
        "accepted": True
    }


def test_maintenance_cli_failure_does_not_print_connection_details(monkeypatch, capsys):
    from app.db import connection, maintenance

    async def noop():
        pass

    async def fail(*args, **kwargs):
        raise RuntimeError("postgresql://user:PRIVATE@host/db")

    monkeypatch.setattr(connection, "open_database_pool", noop)
    monkeypatch.setattr(connection, "close_database_pool", noop)
    monkeypatch.setattr(maintenance, "maintain_database", fail)
    monkeypatch.setattr("sys.argv", ["maintenance"])
    with pytest.raises(SystemExit) as exited:
        maintenance.main()
    assert exited.value.code == 1
    output = capsys.readouterr()
    assert "database_maintenance_failed" in output.err
    assert "PRIVATE" not in output.err and "Traceback" not in output.err
