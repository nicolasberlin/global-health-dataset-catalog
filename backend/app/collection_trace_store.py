"""Bridge collection threads to the same persistence retry/fencing policy as votes."""

from __future__ import annotations

import asyncio

from app.db.collection_traces import write_collection_trace
from app.workers import persist_with_retry
from collector.diagnostics import PersistenceFailure


class PostgresCollectionTrace:
    def __init__(self, loop, job_id, version):
        self.loop, self.job_id, self.version = loop, job_id, version

    def __call__(self, sequence, observation):
        try:
            accepted = asyncio.run_coroutine_threadsafe(
                persist_with_retry(
                    lambda: write_collection_trace(self.job_id, self.version, sequence, observation)
                ),
                self.loop,
            ).result()
            if not accepted:
                raise PersistenceFailure("Collection claim is no longer current.")
        except PersistenceFailure:
            raise
        except Exception as exc:
            raise PersistenceFailure("Collection trace could not be saved.") from exc
