from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectorConfig:
    user_agent: str = "GlobalHealthDatasetCollector/0.1"
    request_timeout_seconds: float = 10.0
    max_sample_bytes: int = 65_536
    max_pages_per_source: int = 5
    max_distributions_per_dataset: int = 1


DEFAULT_CONFIG = CollectorConfig()
