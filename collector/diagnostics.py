"""Stable public diagnostics, independent of transport and database libraries.

Messages are selected here, never copied from external exceptions. Recovery is
advisory: ``manual`` does not bypass admission or promise an available command.
Scheduling and retry budgets are enforced by backend workers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Literal

Stage = Literal["search", "classification", "collection", "validation"]
ExecutionStatus = Literal["queued", "running", "waiting_retry", "finished", "failed"]
Outcome = Literal["results", "empty", "incomplete"]
Recovery = Literal["automatic", "manual", "configuration_required", "none"]

_MESSAGES = {
    "no_download_links": "No downloadable resource links were detected.",
    "page_rejected": "The page did not pass dataset eligibility classification.",
    "browser_unavailable": "The optional browser service is unavailable or not configured.",
    "browser_timeout": "The browser operation timed out.",
    "resource_checks_failed": "Detected resources did not pass validation.",
    "coverage_limited": "Collection stopped at the configured resource limit.",
    "collection_budget_exhausted": "The collection time budget was exhausted.",
    "extraction_limit_exceeded": "The page exceeded safe extraction limits.",
    "extraction_invalid_content": "The page could not be safely extracted.",
    "dataset_identity_ambiguous": "The page could not be matched to a single dataset.",
    "llm_retry_exhausted": "The automatic model retry budget was exhausted.",
    "llm_timeout": "The model request timed out.",
    "llm_network_error": "The model could not be reached.",
    "llm_rate_limited": "The model provider rate limit was reached.",
    "llm_unavailable": "The model provider is unavailable.",
    "llm_invalid_response": "The model did not return a valid classification.",
    "llm_response_too_large": "The model response exceeded the allowed size.",
    "llm_configuration_error": "The model configuration requires attention.",
    "classification_incomplete": "Not all required model votes are available.",
    "repository_unavailable": "A repository could not be queried.",
    "repository_http_error": "The repository returned an unsuccessful HTTP response.",
    "repository_network_error": "The repository connection could not be completed.",
    "repository_timeout": "The repository request timed out.",
    "repository_invalid_json": "The received repository response could not be read as JSON.",
    "repository_response_too_large": "The repository response exceeded the allowed size.",
    "repository_metadata_invalid": "The received metadata does not match the connector format.",
    "browser_invalid_response": "The browser service returned an invalid response.",
    "browser_render_failed": "The browser could not render the page.",
    "browser_navigation_failed": "The browser could not complete page navigation.",
    "browser_worker_exited": "The isolated browser process stopped before completion.",
    "processing_interrupted": "Processing was interrupted.",
    "persistence_failed": "The processing result could not be saved.",
    "processing_failed": "Processing could not be completed.",
    "legacy_unknown": "The stored record does not establish a complete result.",
    "collection_not_scheduled": "No collection is associated with this candidate.",
    "classification_not_requested": "This candidate has not been classified.",
    "verification_unconfirmed": "A required data access check was inconclusive.",
    "access_restricted": "Data access requires authentication or permission.",
    "resource_unavailable": "The data resource is unavailable.",
    "quota_service_unavailable": "The work quota could not be checked.",
    "api_quota_exceeded": "The API work quota was reached.",
    "search_scope_limited": "The search was limited to the configured candidate count.",
    "invalid_repository_metadata": "Some repository records had invalid metadata.",
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    stage: Stage
    recovery: Recovery = "manual"
    retry_at: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    voter_id: str | None = None

    @property
    def message(self) -> str:
        return _MESSAGES.get(self.code, _MESSAGES["processing_failed"])

    def to_dict(self) -> dict:
        return {**asdict(self), "message": self.message}


class PipelineFailure(RuntimeError):
    def __init__(self, message: str, *, diagnostics: list[Diagnostic]):
        super().__init__(message)
        self.diagnostics = diagnostics


class PersistenceFailure(PipelineFailure):
    """Keep a failed storage operation attached to its owning pipeline stage."""

    def __init__(self, message: str, *, stage: Stage = "classification") -> None:
        super().__init__(message, diagnostics=[Diagnostic("persistence_failed", stage)])


def exception_diagnostics(exception: Exception, stage: Stage) -> list[Diagnostic]:
    if isinstance(exception, PipelineFailure):
        return exception.diagnostics
    return [Diagnostic("processing_failed", stage)]


def public_diagnostics(values: list[dict]) -> list[dict]:
    """Rebuild the allowlisted shape; persisted messages are not trusted."""
    fields = ("recovery", "retry_at", "attempt", "max_attempts", "voter_id")
    return [
        Diagnostic(
            code=value["code"] if value.get("code") in _MESSAGES else "processing_failed",
            stage=value["stage"],
            **{key: value[key] for key in fields if key in value},
        ).to_dict()
        for value in values
    ]


def voter_diagnostics(exception: Exception, voter_id: str, attempt=None) -> list[Diagnostic]:
    return [
        replace(item, voter_id=voter_id, attempt=attempt if attempt is not None else item.attempt)
        for item in exception_diagnostics(exception, "classification")
    ]


def retry_after(value: str | None, *, now: datetime | None = None) -> str | None:
    """Preserve a provider's earliest retry date, without scheduling a retry."""
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        value = value.strip()
        if value.isdigit():
            date = now + timedelta(seconds=int(value))
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
        return max(now, date).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None
