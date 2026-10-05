"""Owner-scoped command receipts, committed in the same transaction as admitted work."""

from __future__ import annotations

import hashlib
import json
import re

from .connection import _fetchone
from .serialization import _jsonb


class CommandConflict(ValueError):
    """An idempotency key was reused for a different command."""


def validate_command_key(key: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise ValueError(
            "Idempotency-Key must contain 1 to 128 letters, digits, '.', '_', ':' or '-'."
        )
    return key


def _fingerprint(operation: str, payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {"version": 1, "operation": operation, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


async def read_command(connection, owner_id, key, operation, payload):
    """Lock before quota/resource locks. A replay never reserves work again."""
    validate_command_key(key)
    lock = json.dumps(["collector-command", owner_id, key], separators=(",", ":"))
    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock,))
    row = await _fetchone(
        connection,
        "SELECT fingerprint, result FROM api_commands WHERE owner_id = %s AND command_key = %s",
        (owner_id, key),
    )
    if row is not None and row["fingerprint"] != _fingerprint(operation, payload):
        raise CommandConflict("Idempotency-Key was already used for a different command.")
    return row["result"] if row else None


async def record_command(connection, owner_id, key, operation, payload, result):
    await connection.execute(
        """
        INSERT INTO api_commands (owner_id, command_key, operation, fingerprint, result)
        VALUES (%s, %s, %s, %s, %s)
    """,
        (owner_id, key, operation, _fingerprint(operation, payload), _jsonb(result)),
    )
