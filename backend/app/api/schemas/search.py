"""Search request, candidate, command and progress models with their validation rules."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.api.schemas.classification import (
    CandidateClassificationView,
    VoteProgressView,
)
from app.api.schemas.collection import CollectionFollowUpView
from app.api.schemas.common import ProcessingDiagnosticView
from collector.classification.repository import (
    MAX_REPOSITORY_DATE_CHARS,
    MAX_REPOSITORY_DESCRIPTION_CHARS,
    MAX_REPOSITORY_DOI_CHARS,
    MAX_REPOSITORY_KEYWORD_CHARS,
    MAX_REPOSITORY_KEYWORDS,
    MAX_REPOSITORY_METADATA_BYTES,
    MAX_REPOSITORY_PUBLISHER_CHARS,
    MAX_REPOSITORY_SEARCH_QUERY_CHARS,
    MAX_REPOSITORY_SOURCE_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
)
from collector.diagnostics import ExecutionStatus, Outcome, Stage


class SearchCreateRequest(BaseModel):
    """JSON body accepted by POST /collector/searches; the command key is a header."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_REPOSITORY_SEARCH_QUERY_CHARS)


RepositoryKeyword = Annotated[str, Field(max_length=MAX_REPOSITORY_KEYWORD_CHARS)]


class RepositoryCandidateView(BaseModel):
    """One discovered candidate and its classification/collection state in a snapshot."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    search_id: UUID
    title: str = Field(max_length=MAX_REPOSITORY_TITLE_CHARS)
    description: str = Field(default="", max_length=MAX_REPOSITORY_DESCRIPTION_CHARS)
    url: HttpUrl
    source: str = Field(max_length=MAX_REPOSITORY_SOURCE_CHARS)
    publisher: str = Field(default="", max_length=MAX_REPOSITORY_PUBLISHER_CHARS)
    date: str = Field(default="", max_length=MAX_REPOSITORY_DATE_CHARS)
    doi: str = Field(default="", max_length=MAX_REPOSITORY_DOI_CHARS)
    keywords: list[RepositoryKeyword] = Field(
        default_factory=list,
        max_length=MAX_REPOSITORY_KEYWORDS,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    classification_status: Literal[
        "pending", "queued", "classifying", "accepted", "rejected", "error"
    ] = "pending"
    classification: CandidateClassificationView | None = None
    classification_progress: VoteProgressView = Field(default_factory=VoteProgressView)
    errors: list[ProcessingDiagnosticView] = Field(default_factory=list)
    classification_error: str = Field(default="", max_length=2_000)
    classification_error_code: Literal["", "classification_failed"] = ""
    automatic_collection: CollectionFollowUpView | None = None
    created_at: str = ""
    updated_at: str = ""

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded_metadata = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exception:
            raise ValueError("metadata must be JSON-safe") from exception

        if len(encoded_metadata) > MAX_REPOSITORY_METADATA_BYTES:
            raise ValueError(
                f"metadata must not exceed {MAX_REPOSITORY_METADATA_BYTES} bytes"
            )
        return value


class RepositorySearchWarningView(BaseModel):
    """A non-fatal repository discovery warning with optional provider context."""

    code: str = "repository_unavailable"
    incomplete: bool = True
    message: str
    provider: str | None = None


class SearchProgressResponse(BaseModel):
    """A search snapshot returned by progress, latest and diagnostic reads.

    execution_status describes processing; outcome is results, empty or incomplete
    when known. polling_required tells the client whether to keep requesting updates.
    dataset_ids can be resolved into full records through the catalogue route.
    """

    search_id: UUID
    query: str = ""
    origin: Literal["database", "online"] | None = None
    local_dataset_ids: list[int] = Field(default_factory=list)
    dataset_ids: list[int] = Field(default_factory=list)
    warnings: list[RepositorySearchWarningView] = Field(default_factory=list)
    attempt: int = 1
    created_at: str = ""
    updated_at: str = ""
    polling_required: bool
    execution_status: ExecutionStatus
    outcome: Outcome | None = None
    active_stages: list[Stage]
    errors: list[ProcessingDiagnosticView] = Field(default_factory=list)
    local_result_count: int | None = Field(default=None, ge=0)
    items: list[RepositoryCandidateView]


class SearchSubmissionResponse(BaseModel):
    """A new or replayed command's acknowledgement, with the URL for reading progress."""

    search_id: UUID
    execution_status: ExecutionStatus
    attempt: int
    progress_url: str
