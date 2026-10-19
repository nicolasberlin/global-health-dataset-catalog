"""Owner-scoped reads; this pool never starts workers or applies migrations."""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def decode_cursor(value):
    if not value:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        return datetime.fromisoformat(data["created_at"]), UUID(data["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Invalid history cursor.") from exc


class History:
    def __init__(self, database_url):
        self.pool = AsyncConnectionPool(
            database_url,
            min_size=1,
            max_size=3,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=self._configure,
        )

    @staticmethod
    async def _configure(connection):
        await connection.execute("SET default_transaction_read_only = on")
        await connection.execute("SET statement_timeout = '5s'")

    async def open(self):
        await self.pool.open()
        await self.pool.wait(timeout=5)

    async def close(self):
        await self.pool.close()

    @asynccontextmanager
    async def connection(self):
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                yield connection

    async def list_searches(self, owner_id, *, query="", origin=None, limit=25, cursor=None):
        after = decode_cursor(cursor)
        clauses, params = ["s.owner_id = %s", "s.query ILIKE %s"], [owner_id, "%" + query + "%"]
        if origin:
            clauses.append("s.origin = %s")
            params.append(origin)
        if after:
            clauses.append("(s.created_at, s.id) < (%s, %s)")
            params.extend(after)
        params.append(limit + 1)
        sql = (
            """
            SELECT s.id, s.query, s.origin, s.status, s.attempt_number,
                   s.created_at, s.updated_at, s.finished_at,
                   (SELECT count(*) FROM repository_candidates c
                    WHERE c.search_session_id = s.id) AS candidate_count
            FROM search_sessions s WHERE """
            + " AND ".join(clauses)
            + """
            ORDER BY s.created_at DESC, s.id DESC LIMIT %s
        """
        )
        async with self.connection() as connection:
            rows = await (await connection.execute(sql, params)).fetchall()
        more, rows = len(rows) > limit, rows[:limit]
        next_cursor = None
        if more:
            last = rows[-1]
            next_cursor = (
                base64.urlsafe_b64encode(
                    json.dumps(
                        {
                            "created_at": last["created_at"].isoformat(),
                            "id": str(last["id"]),
                        }
                    ).encode()
                )
                .decode()
                .rstrip("=")
            )
        return {"items": rows, "next_cursor": next_cursor}

    async def owns_search(self, owner_id, search_id):
        async with self.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT id FROM search_sessions WHERE id = %s AND owner_id = %s",
                    (search_id, owner_id),
                )
            ).fetchone()
        return row is not None

    async def method_claims(self, job_ids):
        if not job_ids:
            return {}
        async with self.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT id, claim_version FROM collection_method_attempts "
                    "WHERE job_id = ANY(%s::integer[])",
                    (job_ids,),
                )
            ).fetchall()
        return {str(row["id"]): row["claim_version"].isoformat() for row in rows}
