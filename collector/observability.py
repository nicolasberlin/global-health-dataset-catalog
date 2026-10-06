"""Small, server-side operational events with no request or response content."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

logger = logging.getLogger("collector.operations")
_context: ContextVar[dict | None] = ContextVar("operation_context", default=None)


def configure_operational_logging() -> None:
    """Enable JSON lines on stderr without changing other application loggers."""
    try:
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)
        logger.propagate = False
    except Exception:
        pass  # Diagnostics must never prevent application startup or work.


def emit_event(
    event: str, *, outcome: str, duration_seconds: float | None = None,
    retry_count: int | None = None, delay_seconds: float | None = None,
) -> None:
    """Only accept bounded measurements, categories and internal correlation IDs.

    Callers supply literal event/outcome categories, never exception text, URLs,
    prompts, model output, credentials or provider configuration.
    """
    try:
        record = {"event": event, "outcome": outcome, **(_context.get() or {})}
        for name, value in (
            ("duration_seconds", duration_seconds), ("retry_count", retry_count),
            ("delay_seconds", delay_seconds),
        ):
            if value is not None:
                record[name] = value
        logger.info(json.dumps(record, separators=(",", ":")))
    except Exception:
        pass  # A broken handler must not turn successful work into a failure.


@contextmanager
def operation_context(*, job_id=None, candidate_id=None):
    values = {key: value for key, value in (
        ("job_id", job_id),
        ("candidate_id", str(candidate_id) if candidate_id is not None else None),
    ) if value is not None}
    token = _context.set({**(_context.get() or {}), **values})
    try:
        yield
    finally:
        _context.reset(token)


@contextmanager
def measure_operation(event: str):
    started = monotonic()
    result = {"outcome": "success"}
    try:
        yield result
    except BaseException:
        if result["outcome"] == "success":
            result["outcome"] = "failed"
        raise
    finally:
        emit_event(event, outcome=result["outcome"],
                   duration_seconds=max(0.0, monotonic() - started))
