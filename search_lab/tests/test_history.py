from uuid import uuid4

import psycopg
import pytest

from search_lab.backend.history import decode_cursor

pytestmark = pytest.mark.anyio


async def test_history_is_owner_scoped_filtered_and_cursor_paginated(history_db):
    history, url = history_db
    ids = sorted([uuid4(), uuid4()], reverse=True)
    with psycopg.connect(url, autocommit=True) as writer:
        for identifier, owner, origin in [
            (ids[0], "alice", "online"),
            (ids[1], "alice", "online"),
            (uuid4(), "bob", "online"),
            (uuid4(), "alice", "database"),
        ]:
            writer.execute(
                "INSERT INTO search_sessions(id,owner_id,query,origin,status,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (identifier, owner, "HIV", origin, "completed", "2026-10-09T10:00:00Z"),
            )
    first = await history.list_searches("alice", query="HIV", origin="online", limit=1)
    assert [row["id"] for row in first["items"]] == [ids[0]]
    second = await history.list_searches(
        "alice", origin="online", limit=1, cursor=first["next_cursor"]
    )
    assert [row["id"] for row in second["items"]] == [ids[1]]
    assert second["next_cursor"] is None
    assert await history.owns_search("alice", ids[0])
    assert not await history.owns_search("bob", ids[0])
    assert not (await history.list_searches("alice", query="' OR TRUE --"))["items"]


async def test_lab_connection_cannot_write(history_db):
    history, _ = history_db
    async with history.connection() as connection:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await connection.execute("DELETE FROM search_sessions")


@pytest.mark.parametrize("cursor", ["garbage", "e30", "bnVsbA", "W10"])
async def test_invalid_cursor_is_rejected(cursor):
    with pytest.raises(ValueError):
        decode_cursor(cursor)
