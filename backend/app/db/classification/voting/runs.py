"""Prepare reusable vote runs and their configured voters in one transaction."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from app.db.classification.voting.state import _publish_progress, _scope
from app.db.connection import _fetchone, _require_database_pool
from app.db.serialization import _jsonb


async def prepare_vote_run(snapshot, *, candidate_id=None, job_id=None, expected_updated_at=None):
    """Create or reuse a scoped run and publish its initial vote progress atomically."""
    if (candidate_id is None) == (job_id is None):
        raise ValueError("Exactly one classification scope is required.")
    fingerprint = hashlib.sha256(
        json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    voter_ids = [item["voter_id"] for item in snapshot["configuration"]]
    if not voter_ids or len(voter_ids) != len(set(voter_ids)):
        raise ValueError("Vote identifiers must be non-empty and unique.")
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            scope = await _scope(connection, candidate_id, job_id, expected_updated_at)
            column = "repository_candidate_id" if candidate_id is not None else "collection_job_id"
            await connection.execute(
                f"INSERT INTO classification_runs (id, {column}, fingerprint, snapshot) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (uuid4(), scope["id"], fingerprint, _jsonb(snapshot)),
            )
            run = await _fetchone(
                connection,
                f"SELECT id FROM classification_runs WHERE {column} = %s AND fingerprint = %s "
                "FOR UPDATE",
                (scope["id"], fingerprint),
            )
            await connection.execute(
                "INSERT INTO classification_votes (run_id, voter_id) "
                "SELECT %s, unnest(%s::text[]) ON CONFLICT DO NOTHING",
                (run["id"], voter_ids),
            )
            await _publish_progress(connection, run["id"], candidate_id, job_id)
    return run["id"]
