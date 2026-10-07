"""Durable receipts for sequential retries of one worker acquisition."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from .connection import Row, _fetchone

Queue = Literal["search", "classification", "collection"]


async def read_worker_claim(
    connection: AsyncConnection[DictRow], token: UUID, queue: Queue,
) -> Row | None:
    """Call inside a transaction, before taking any task row locks."""
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"worker-claim:{token}",),
    )
    receipt = await _fetchone(
        connection, "SELECT * FROM worker_claims WHERE token = %s", (token,),
    )
    if receipt is not None and receipt["queue"] != queue:
        raise ValueError("Worker claim token belongs to another queue.")
    return receipt


async def record_worker_claim(
    connection: AsyncConnection[DictRow], token: UUID, queue: Queue,
    resource_id: object, claim_version: datetime,
) -> None:
    """Commit the receipt and task transition together; empty polls need no receipt."""
    await connection.execute(
        """INSERT INTO worker_claims (token, queue, resource_id, claim_version)
           VALUES (%s, %s, %s, %s)""",
        (token, queue, str(resource_id), claim_version),
    )
