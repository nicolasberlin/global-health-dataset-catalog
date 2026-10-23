from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from collector.classification.repository import (
    MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS,
    MAX_REPOSITORY_DATE_CHARS,
    MAX_REPOSITORY_DESCRIPTION_CHARS,
    MAX_REPOSITORY_DOI_CHARS,
    MAX_REPOSITORY_KEYWORD_CHARS,
    MAX_REPOSITORY_KEYWORDS,
    MAX_REPOSITORY_METADATA_BYTES,
    MAX_REPOSITORY_MISSING_INFORMATION_CHARS,
    MAX_REPOSITORY_MISSING_INFORMATION_ITEMS,
    MAX_REPOSITORY_PUBLISHER_CHARS,
    MAX_REPOSITORY_SEARCH_QUERY_CHARS,
    MAX_REPOSITORY_SOURCE_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
    REPOSITORY_ACCEPTED_RELEVANCE_LABELS,
    RepositoryRelevanceLabel,
)
from collector.diagnostics import ExecutionStatus, Outcome, Recovery, Stage


class CollectorDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    stage: Stage
    message: str
    recovery: Recovery
    retry_at: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    voter_id: str | None = None


# Query-driven repository search endpoint.
class CollectorRepositorySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_REPOSITORY_SEARCH_QUERY_CHARS)


RepositoryKeyword = Annotated[str, Field(max_length=MAX_REPOSITORY_KEYWORD_CHARS)]
RepositoryMissingInformation = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REPOSITORY_MISSING_INFORMATION_CHARS),
]
RepositoryVoterId = Annotated[str, Field(min_length=1, max_length=100)]


class CollectorRepositoryClassificationVote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voter_id: RepositoryVoterId
    accepted: bool
    relevance_label: RepositoryRelevanceLabel
    reason: str = Field(
        min_length=1,
        max_length=MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS,
    )
    missing_information: list[RepositoryMissingInformation] = Field(
        default_factory=list,
        max_length=MAX_REPOSITORY_MISSING_INFORMATION_ITEMS,
    )

    @model_validator(mode="after")
    def validate_decision(self) -> CollectorRepositoryClassificationVote:
        expected_accepted = (
            self.relevance_label in REPOSITORY_ACCEPTED_RELEVANCE_LABELS
        )
        if self.accepted is not expected_accepted:
            raise ValueError("accepted must match relevance_label")
        if self.relevance_label == "insufficient_information":
            if not self.missing_information:
                raise ValueError(
                    "insufficient_information must identify missing information"
                )
        elif self.missing_information:
            raise ValueError(
                "missing_information must be empty for this relevance_label"
            )
        return self


class CollectorRepositoryClassificationFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voter_id: RepositoryVoterId
    error: str = Field(min_length=1, max_length=2_000)
    error_code: Literal["classifier_vote_failed"] = "classifier_vote_failed"
    errors: list[CollectorDiagnostic] = Field(default_factory=list)


class CollectorRepositoryClassificationEnsemble(BaseModel):
    model_config = ConfigDict(extra="forbid")

    votes_required: int = Field(ge=1, le=10)
    minimum_successful_votes: int = Field(ge=1, le=10)
    successful_votes: int = Field(ge=0, le=10)
    failed_votes: int = Field(ge=0, le=10)
    accepted_votes: int = Field(ge=0, le=10)
    decision: Literal["accepted", "rejected"]
    decision_reason: Literal[
        "enough_accept_votes",
        "rejected_by_majority",
        "insufficient_accept_votes",
    ]
    decision_voter_ids: list[RepositoryVoterId] = Field(
        default_factory=list,
        max_length=10,
    )
    voters: list[CollectorRepositoryClassificationVote] = Field(
        default_factory=list,
        max_length=10,
    )
    failures: list[CollectorRepositoryClassificationFailure] = Field(
        default_factory=list,
        max_length=10,
    )


class CollectorRepositoryClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    relevance_label: RepositoryRelevanceLabel
    reason: str = Field(
        min_length=1,
        max_length=MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS,
    )
    missing_information: list[RepositoryMissingInformation] = Field(
        default_factory=list,
        max_length=MAX_REPOSITORY_MISSING_INFORMATION_ITEMS,
    )
    ensemble: CollectorRepositoryClassificationEnsemble

    @model_validator(mode="after")
    def validate_decision(self) -> CollectorRepositoryClassification:
        expected_accepted = (
            self.relevance_label in REPOSITORY_ACCEPTED_RELEVANCE_LABELS
        )
        if self.accepted is not expected_accepted:
            raise ValueError("accepted must match relevance_label")
        if self.relevance_label == "insufficient_information":
            if not self.missing_information:
                raise ValueError(
                    "insufficient_information must identify missing information"
                )
        elif self.missing_information:
            raise ValueError(
                "missing_information must be empty for this relevance_label"
            )
        if self.accepted is not (self.ensemble.decision == "accepted"):
            raise ValueError("accepted must match the ensemble decision")
        return self


class CollectorVoteProgress(BaseModel):
    total: int = Field(default=0, ge=0, le=10)
    succeeded: int = Field(default=0, ge=0, le=10)
    failed: int = Field(default=0, ge=0, le=10)


class CollectorCollectionJob(BaseModel):
    """Public job view; internal rows must pass through the response presenter."""

    model_config = ConfigDict(extra="forbid")

    id: int
    source_url: str
    kind: Literal["source", "repository_candidate"] = "source"
    status: Literal["pending", "running", "done", "error"]
    execution_status: ExecutionStatus
    outcome: Outcome | None = None
    errors: list[CollectorDiagnostic] = Field(default_factory=list)
    saved_count: int
    classification_progress: CollectorVoteProgress = Field(default_factory=CollectorVoteProgress)
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


class CollectorAutomaticCollection(BaseModel):
    execution_status: ExecutionStatus
    outcome: Outcome | None = None
    errors: list[CollectorDiagnostic] = Field(default_factory=list)
    dataset_ids: list[int] = Field(default_factory=list)
    state: Literal["pending", "running", "saved", "empty", "error"]
    job: CollectorCollectionJob | None = None
    error: str = Field(default="", max_length=2_000)
    error_code: Literal["", "collection_scheduling_failed", "collection_not_scheduled"] = ""


class CollectorRepositorySearchItem(BaseModel):
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
    classification: CollectorRepositoryClassification | None = None
    classification_progress: CollectorVoteProgress = Field(default_factory=CollectorVoteProgress)
    errors: list[CollectorDiagnostic] = Field(default_factory=list)
    classification_error: str = Field(default="", max_length=2_000)
    classification_error_code: Literal["", "classification_failed"] = ""
    automatic_collection: CollectorAutomaticCollection | None = None
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


class CollectorRepositorySearchWarning(BaseModel):
    code: str = "repository_unavailable"
    incomplete: bool = True
    message: str
    provider: str | None = None


class CollectorDistribution(BaseModel):
    url: str
    format: str
    probability: float
    anchor: str = ""
    mime_type: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_checked_at: str = ""


class CollectorValidation(BaseModel):
    url: str
    final_url: str
    format: str
    ok: bool
    status: Literal["available", "restricted", "unavailable", "unconfirmed"] = "unconfirmed"
    reason: str = ""
    http_status: int | None
    mime_type: str = ""
    size_bytes: int | None = None
    etag: str = ""
    last_modified: str = ""
    content_disposition: str = ""
    error: str = ""
    error_code: Literal["", "validation_failed"] = ""


class CollectorCollectedDataset(BaseModel):
    id: int | None = None
    source_url: str = ""
    dataset_url: HttpUrl
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    geography: list[str] = Field(default_factory=list)
    date_of_publication: str = ""
    sharing_license: str = ""
    doi: str = ""
    metadata_provenance: dict[str, Any] = Field(default_factory=dict)
    record_identity: dict[str, str] = Field(default_factory=dict)
    discovery_method: str
    dataset_signals: dict[str, Any]
    distributions: list[CollectorDistribution]
    validation_results: list[CollectorValidation]
    first_seen_at: str = ""
    last_seen_at: str = ""
    updated_at: str = ""


class CollectorCollectionResponse(BaseModel):
    next_cursor: int | None = None
    items: list[CollectorCollectedDataset]


class CollectorSearchProgressResponse(BaseModel):
    search_id: UUID
    query: str = ""
    origin: Literal["database", "online"] | None = None
    local_dataset_ids: list[int] = Field(default_factory=list)
    dataset_ids: list[int] = Field(default_factory=list)
    warnings: list[CollectorRepositorySearchWarning] = Field(default_factory=list)
    attempt: int = 1
    created_at: str = ""
    updated_at: str = ""
    polling_required: bool
    execution_status: ExecutionStatus
    outcome: Outcome | None = None
    active_stages: list[Stage]
    errors: list[CollectorDiagnostic] = Field(default_factory=list)
    local_result_count: int | None = Field(default=None, ge=0)
    items: list[CollectorRepositorySearchItem]


class CollectorSearchCreateRequest(CollectorRepositorySearchRequest):
    model_config = ConfigDict(extra="forbid")


class CollectorSearchCommandResponse(BaseModel):
    search_id: UUID
    execution_status: ExecutionStatus
    attempt: int
    progress_url: str


class CollectorHTTPError(BaseModel):
    detail: str
