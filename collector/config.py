from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CollectorConfig:
    user_agent: str = "GlobalHealthDatasetCollector/0.1"
    request_timeout_seconds: float = 10.0
    record_request_timeout_seconds: float = 20.0
    record_max_attempts: int = 3
    record_retry_max_wait_seconds: float = 30.0
    max_sample_bytes: int = 65_536
    max_pages_per_source: int = 5
    max_distribution_attempts: int = 3
    max_distributions_saved: int = 1
    collection_max_duration_seconds: float = 300.0
    dataverse_hosts: tuple[str, ...] = ("dataverse.harvard.edu", "dataverse.unc.edu")
    zenodo_hosts: tuple[str, ...] = ("zenodo.org",)
    figshare_hosts: tuple[str, ...] = ("figshare.com", "springernature.figshare.com")
    inveniordm_hosts: tuple[str, ...] = (
        "researchdata.tuwien.ac.at", "data.caltech.edu", "repository.cern",
    )
    dspace_api_bases: tuple[tuple[str, str], ...] = (
        ("demo.dspace.org", "https://demo.dspace.org/server/api"),
        ("www.zora.uzh.ch", "https://www.zora.uzh.ch/server/api"),
        ("iris.unil.ch", "https://api.unil.ch/iris/server/api"),
    )

    def __post_init__(self):
        validate_collection_budget_seconds(self.collection_max_duration_seconds)
        if (not math.isfinite(self.record_request_timeout_seconds)
                or not 1 <= self.record_request_timeout_seconds <= 120):
            raise ValueError("Record request timeout must be between 1 and 120 seconds.")
        if type(self.record_max_attempts) is not int or not 1 <= self.record_max_attempts <= 3:
            raise ValueError("Record maximum attempts must be between 1 and 3.")
        if (not math.isfinite(self.record_retry_max_wait_seconds)
                or not 0 <= self.record_retry_max_wait_seconds <= 60):
            raise ValueError("Record retry wait must be between 0 and 60 seconds.")


def validate_collection_budget_seconds(value: float) -> float:
    if not math.isfinite(value) or not 1 <= value <= 3600:
        raise ValueError("Collection duration must be finite and between 1 and 3600 seconds.")
    return value


def configured_collection_budget_seconds() -> float:
    return validate_collection_budget_seconds(
        float(os.getenv("COLLECTION_MAX_DURATION_SECONDS", "300"))
    )


DEFAULT_CONFIG = CollectorConfig()


def configured_record_transport() -> dict[str, float | int]:
    values = {
        "record_request_timeout_seconds": float(
            os.getenv("COLLECTION_RECORD_TIMEOUT_SECONDS", "20")
        ),
        "record_max_attempts": int(os.getenv("COLLECTION_RECORD_MAX_ATTEMPTS", "3")),
        "record_retry_max_wait_seconds": float(
            os.getenv("COLLECTION_RECORD_MAX_WAIT_SECONDS", "30")
        ),
    }
    CollectorConfig(**values)  # Validate before starting any network operations.
    return values


def configured_repository_connectors() -> dict:
    result = {}
    for field, variable in (
        ("figshare_hosts", "COLLECTION_FIGSHARE_HOSTS"),
        ("inveniordm_hosts", "COLLECTION_INVENIORDM_HOSTS"),
    ):
        result[field] = tuple(
            host.strip() for host in os.getenv(
                variable, ",".join(getattr(DEFAULT_CONFIG, field)),
            ).split(",") if host.strip()
        )
    bases = json.loads(os.getenv(
        "COLLECTION_DSPACE_API_BASES", json.dumps(dict(DEFAULT_CONFIG.dspace_api_bases)),
    ))
    if not isinstance(bases, dict) or any(
        not isinstance(host, str) or not isinstance(base, str) for host, base in bases.items()
    ):
        raise ValueError("DSpace API bases must map hostnames to API URLs")
    result["dspace_api_bases"] = tuple(bases.items())
    return result
