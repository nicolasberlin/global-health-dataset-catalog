from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectorConfig:
    user_agent: str = "GlobalHealthDatasetCollector/0.1"
    request_timeout_seconds: float = 10.0
    max_sample_bytes: int = 65_536
    min_dataset_probability: float = 0.6
    min_health_probability: float = 0.35
    max_pages_per_source: int = 500
    max_crawl_depth: int = 3


DEFAULT_CONFIG = CollectorConfig()

