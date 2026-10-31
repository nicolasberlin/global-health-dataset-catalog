"""Diagnostic and HTTP error models shared by API domains."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from collector.diagnostics import Recovery, Stage


class ProcessingDiagnosticView(BaseModel):
    """A controlled processing error or warning that can be sent to the client."""

    model_config = ConfigDict(extra="forbid")

    code: str
    stage: Stage
    message: str
    recovery: Recovery
    retry_at: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    voter_id: str | None = None


class HttpErrorResponse(BaseModel):
    """The simple JSON error shape documented for controlled command failures."""

    detail: str
