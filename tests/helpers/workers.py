"""Small worker doubles and construction helpers for runtime regression tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock


@dataclass
class StubWorker:
    name: str = "test"
    claim: Any = field(default_factory=AsyncMock)
    execute: Any = field(default_factory=AsyncMock)
    recover: Any = field(
        default_factory=lambda: AsyncMock(side_effect=AssertionError("Unexpected worker recovery"))
    )


def make_worker(module: ModuleType, **dependencies):
    for name in ("SearchWorker", "ClassificationWorker", "CollectionWorker"):
        if worker_type := getattr(module, name, None):
            return worker_type(**dependencies)
    raise ValueError(f"No worker implementation in {module.__name__}")


async def execute_worker(module, job, executor):
    return await make_worker(module).execute(job, executor)
