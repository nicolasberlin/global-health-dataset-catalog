from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CollectorConfig:
    user_agent: str = "GlobalHealthDatasetCollector/0.1"
    request_timeout_seconds: float = 10.0
    max_sample_bytes: int = 65_536
    max_pages_per_source: int = 5
    max_distribution_attempts: int = 3
    max_distributions_saved: int = 1
    collection_max_duration_seconds: float = 180.0

    def __post_init__(self):
        validate_collection_budget_seconds(self.collection_max_duration_seconds)


def validate_collection_budget_seconds(value: float) -> float:
    if not math.isfinite(value) or not 1 <= value <= 3600:
        raise ValueError("Collection duration must be finite and between 1 and 3600 seconds.")
    return value


def configured_collection_budget_seconds() -> float:
    return validate_collection_budget_seconds(
        float(os.getenv("COLLECTION_MAX_DURATION_SECONDS", "180"))
    )


DEFAULT_CONFIG = CollectorConfig()
