"""Bounded LLM recovery; provider deadlines are never shortened."""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.quota_policy import QuotaExceeded
from collector.diagnostics import Diagnostic

TRANSIENT = {"llm_timeout", "llm_network_error", "llm_rate_limited", "llm_unavailable"}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    invalid_attempts: int = 2
    window_seconds: float = 120

    @classmethod
    def configured(cls):
        max_attempts = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
        policy = cls(
            max_attempts,
            int(os.getenv("LLM_INVALID_MAX_ATTEMPTS", str(min(2, max_attempts)))),
            float(os.getenv("LLM_RETRY_WINDOW_SECONDS", "120")),
        )
        if (
            not 1 <= policy.max_attempts <= 10
            or not 1 <= policy.invalid_attempts <= policy.max_attempts
            or not math.isfinite(policy.window_seconds)
            or not 1 <= policy.window_seconds <= 3600
        ):
            raise ValueError("Invalid LLM retry policy.")
        return policy

    def limit(self, code):
        return (
            self.max_attempts
            if code in TRANSIENT
            else self.invalid_attempts
            if code == "llm_invalid_response"
            else 1
        )


def as_datetime(value):
    if value is None:
        return None
    date = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date


def enforce_retry_date(errors, *, now=None):
    now = now or datetime.now(timezone.utc)
    dates = [as_datetime(item.get("retry_at")) for item in errors if item.get("retry_at")]
    if dates and max(dates) > now:
        raise QuotaExceeded(
            math.ceil((max(dates) - now).total_seconds()), "The retry is not due yet."
        )


def plan_retry(errors: list[Diagnostic], *, round_number, started_at, now=None, policy=None):
    """Return a due time and diagnostics; None means no automatic continuation."""
    policy = policy or RetryPolicy.configured()
    now = now or datetime.now(timezone.utc)
    errors = [
        replace(item, recovery="manual") if item.recovery == "automatic" else item
        for item in errors
    ]
    relevant = [item for item in errors if item.code != "classification_incomplete"]
    if not relevant:
        return None, errors
    errors = [
        replace(item, max_attempts=policy.limit(item.code))
        if item.code in TRANSIENT | {"llm_invalid_response"}
        else item
        for item in errors
    ]
    if round_number + 1 >= policy.max_attempts or any(
        item.code not in TRANSIENT | {"llm_invalid_response"}
        or (item.attempt or 1) >= policy.limit(item.code)
        for item in relevant
    ):
        return None, errors
    delay = (2 if round_number == 0 else 5) * random.uniform(1, 1.25)
    due = max(
        [now + timedelta(seconds=delay)]
        + [as_datetime(item.retry_at) for item in relevant if item.retry_at]
    )
    deadline = as_datetime(started_at) + timedelta(seconds=policy.window_seconds)
    if due >= deadline:
        return None, errors
    return due, [replace(item, recovery="automatic", retry_at=due.isoformat()) for item in errors]
