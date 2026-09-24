"""Quota configuration shared by HTTP access and transactional work admission."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class QuotaLimit:
    owner_id: str
    operation: str
    limit: int
    window: Literal["minute", "day"] = "minute"


@dataclass(frozen=True)
class WorkAdmission:
    quotas: tuple[QuotaLimit, ...]
    max_active: int | None = None
    max_candidates: int | None = None


class QuotaExceeded(Exception):
    def __init__(self, retry_after_seconds: int, message: str = "API request quota exceeded."):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class QuotaUnavailable(Exception):
    """A quota could not be checked; callers must not start external work."""


_OWNER_LIMITS = {
    "repository_search": ("API_SEARCH_REQUESTS_PER_MINUTE", 10),
    "repository_classification": ("API_CLASSIFICATION_REQUESTS_PER_MINUTE", 20),
}
_PUBLIC_LIMITS = {
    "session": ("API_PUBLIC_SESSIONS_PER_IP_PER_MINUTE", 20),
    "repository_search": ("API_PUBLIC_SEARCHES_PER_IP_PER_MINUTE", 30),
    "repository_classification": ("API_PUBLIC_CLASSIFICATIONS_PER_IP_PER_MINUTE", 60),
    "online_daily": ("API_PUBLIC_ONLINE_SEARCHES_PER_DAY", 500),
    "work_daily": ("API_PUBLIC_WORK_ITEMS_PER_DAY", 500),
    "active": ("API_PUBLIC_MAX_ACTIVE_WORK_ITEMS", 100),
    "candidates": ("API_PUBLIC_MAX_CANDIDATES_PER_SEARCH", 10),
}


def owner_quota(owner_id: str, operation: str) -> QuotaLimit:
    return QuotaLimit(owner_id, operation, _limit(*_OWNER_LIMITS[operation], maximum=10_000))


def public_ip_quota(client_key: str, operation: str) -> QuotaLimit:
    return QuotaLimit(client_key, operation, _limit(*_PUBLIC_LIMITS[operation]))


def public_daily_quota(operation: Literal["online_daily", "work_daily"]) -> QuotaLimit:
    return QuotaLimit("public:global", operation, _limit(*_PUBLIC_LIMITS[operation]), window="day")


def classification_admission(owner_id: str, client_key: str | None) -> WorkAdmission:
    quotas = (owner_quota(owner_id, "repository_classification"),)
    if client_key is None:
        return WorkAdmission(quotas)
    return WorkAdmission(
        quotas=(*quotas, public_ip_quota(client_key, "repository_classification"),
                public_daily_quota("work_daily")),
        max_active=_limit(*_PUBLIC_LIMITS["active"]),
        max_candidates=_limit(*_PUBLIC_LIMITS["candidates"]),
    )


def validate_quota_configuration(*, public: bool) -> None:
    for setting in _OWNER_LIMITS.values():
        _limit(*setting, maximum=10_000)
    if public:
        for setting in _PUBLIC_LIMITS.values():
            _limit(*setting)


def _limit(name: str, default: int, *, maximum: int = 1_000_000) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exception:
        raise RuntimeError(f"{name} must be an integer.") from exception
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}.")
    return value
