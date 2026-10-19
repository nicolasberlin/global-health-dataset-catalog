from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from search_lab.backend.history import History


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def history_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for isolated laboratory PostgreSQL tests.")
    schema = "lab_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    target = make_conninfo(url, options="-c search_path=" + schema)
    with psycopg.connect(target, autocommit=True) as writer:
        writer.execute("""
            CREATE TABLE search_sessions (
                id uuid PRIMARY KEY, owner_id text, query text, origin text, status text,
                attempt_number integer DEFAULT 1, created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now(), finished_at timestamptz
            );
            CREATE TABLE repository_candidates (id uuid, search_session_id uuid);
            CREATE TABLE collection_method_attempts (
                id uuid, job_id integer, claim_version timestamptz
            );
        """)
    history = History(target)
    await history.open()
    try:
        yield history, target
    finally:
        await history.close()
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
