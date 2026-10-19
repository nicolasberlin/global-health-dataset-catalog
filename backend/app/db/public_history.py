"""Explicit, bounded public contracts for stored diagnostic history."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from collector.diagnostics import Diagnostic, public_diagnostics


@dataclass(frozen=True)
class HistoryPage:
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("History limit must be between 1 and 200.")
        if type(self.offset) is not int or not 0 <= self.offset <= 10_000:
            raise ValueError("History offset must be between 0 and 10000.")

    def metadata(self, has_more: bool) -> dict:
        following = self.offset + self.limit
        return {
            "history_truncated": has_more,
            "limit": self.limit,
            "offset": self.offset,
            "next_offset": following if has_more and following <= 10_000 else None,
        }


def public_label(value: object, *, maximum: int = 200) -> str:
    """Keep bounded model/format identifiers, excluding URLs and control characters."""
    if not isinstance(value, str) or len(value) > maximum or "://" in value:
        return ""
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._:/+()-]*", value) else ""


def public_timestamp(value: object) -> str | None:
    if isinstance(value, str):
        if len(value) > 64:
            return None
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.isoformat()


def public_identifier(value: object) -> str | None:
    try:
        return str(UUID(str(value))) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def bounded_diagnostics(values: object, *, stage: str = "classification") -> list[dict]:
    """Stored diagnostic fields and messages are untrusted, including legacy rows."""
    if not isinstance(values, list):
        return []
    result = []
    for value in values[:20]:
        if not isinstance(value, dict):
            continue
        clean = {"code": value.get("code", "processing_failed"), "stage": stage}
        if not isinstance(clean["code"], str):
            clean["code"] = "processing_failed"
        if isinstance(value.get("stage"), str) and value["stage"] in {
            "search",
            "classification",
            "collection",
            "validation",
        }:
            clean["stage"] = value["stage"]
        if isinstance(value.get("recovery"), str) and value["recovery"] in {
            "automatic",
            "manual",
            "configuration_required",
            "none",
        }:
            clean["recovery"] = value["recovery"]
        for field in ("attempt", "max_attempts"):
            number = value.get(field)
            if type(number) is int and 1 <= number <= 1_000_000:
                clean[field] = number
        retry = public_timestamp(value.get("retry_at"))
        if retry is not None:
            clean["retry_at"] = retry
        voter = public_label(value.get("voter_id"), maximum=100)
        if voter:
            clean["voter_id"] = voter
        result.extend(public_diagnostics([clean]))
    return result


@dataclass(frozen=True)
class PublicVoteAttempt:
    run_id: str | None
    voter_id: str
    attempt: int
    retry_cycle: str | None
    model: str
    status: str
    started_at: str | None
    finished_at: str | None
    errors: list[dict]
    evidence: str

    @classmethod
    def from_row(cls, row: dict) -> PublicVoteAttempt:
        status = row.get("status")
        if not isinstance(status, str) or status not in {
            "running",
            "succeeded",
            "error",
            "interrupted",
        }:
            status = "error"
        errors = bounded_diagnostics(row.get("errors"))
        if status in {"error", "interrupted"} and not errors:
            code = "processing_interrupted" if status == "interrupted" else "legacy_unknown"
            errors = [Diagnostic(code, "classification").to_dict()]
        attempt = row.get("attempt")
        return cls(
            run_id=public_identifier(row.get("run_id")),
            voter_id=public_label(row.get("voter_id"), maximum=100),
            attempt=attempt if type(attempt) is int and attempt > 0 else 0,
            retry_cycle=public_identifier(row.get("retry_cycle")),
            model=public_label(row.get("model")),
            status=status,
            started_at=public_timestamp(row.get("started_at")),
            finished_at=public_timestamp(row.get("finished_at")),
            errors=errors,
            evidence=("live" if row.get("evidence") == "live" else "legacy_snapshot"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
