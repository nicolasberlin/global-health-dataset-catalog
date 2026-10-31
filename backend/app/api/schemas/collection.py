"""Collection job and automatic follow-up response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.classification import VoteProgressView
from app.api.schemas.common import ProcessingDiagnosticView
from collector.diagnostics import ExecutionStatus, Outcome


class CollectionJobView(BaseModel):
    """Public job view; internal rows must pass through the response presenter."""

    model_config = ConfigDict(extra="forbid")

    id: int
    source_url: str
    kind: Literal["source", "repository_candidate"] = "source"
    status: Literal["pending", "running", "done", "error"]
    execution_status: ExecutionStatus
    outcome: Outcome | None = None
    errors: list[ProcessingDiagnosticView] = Field(default_factory=list)
    saved_count: int
    classification_progress: VoteProgressView = Field(default_factory=VoteProgressView)
    dataset_ids: list[int] = Field(default_factory=list)
    discovered_count: int = 0
    analyzed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    invalid_distribution_count: int = 0
    discovery_methods: list[str] = Field(default_factory=list)
    method_attempts: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error: str = ""
    error_code: Literal["", "collection_failed"] = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""


class CollectionFollowUpView(BaseModel):
    """The collection associated with a candidate, including already-saved datasets."""

    execution_status: ExecutionStatus
    outcome: Outcome | None = None
    errors: list[ProcessingDiagnosticView] = Field(default_factory=list)
    dataset_ids: list[int] = Field(default_factory=list)
    state: Literal["pending", "running", "saved", "empty", "error"]
    job: CollectionJobView | None = None
    error: str = Field(default="", max_length=2_000)
    error_code: Literal["", "collection_scheduling_failed", "collection_not_scheduled"] = ""
