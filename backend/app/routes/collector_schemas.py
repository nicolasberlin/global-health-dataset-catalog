from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Optional
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


# Query-driven repository search endpoint.
class CollectorRepositorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_REPOSITORY_SEARCH_QUERY_CHARS)


class CollectorRepositoryCandidateClassificationRequest(BaseModel):
    """Empty body contract that rejects browser-supplied candidate metadata."""

    model_config = ConfigDict(extra="forbid")


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


class CollectorCollectionJob(BaseModel):
    id: int
    source_url: str
    kind: Literal["source", "repository_candidate"] = "source"
    repository_candidate_id: Optional[UUID] = None  # noqa: UP045
    status: str
    saved_count: int
    discovered_count: int = 0
    analyzed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    invalid_distribution_count: int = 0
    discovery_methods: list[str] = Field(default_factory=list)
    message: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""


class CollectorAutomaticCollection(BaseModel):
    state: Literal["pending", "running", "saved", "empty", "error"]
    job: Optional[CollectorCollectionJob] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    error: str = Field(default="", max_length=2_000)


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
        "pending", "classifying", "accepted", "rejected", "error"
    ] = "pending"
    classification: Optional[CollectorRepositoryClassification] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    classification_error: str = Field(default="", max_length=2_000)
    automatic_collection: Optional[CollectorAutomaticCollection] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
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
    message: str
    provider: Optional[str] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.


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
    http_status: Optional[int]  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    mime_type: str = ""
    size_bytes: Optional[int] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    etag: str = ""
    last_modified: str = ""
    content_disposition: str = ""
    error: str = ""


class CollectorCollectedDataset(BaseModel):
    id: Optional[int] = None  # noqa: UP045 - Pydantic evaluates this on Python 3.9.
    source_url: str = ""
    dataset_url: HttpUrl
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    geography: list[str] = Field(default_factory=list)
    discovery_method: str
    dataset_signals: dict[str, Any]
    distributions: list[CollectorDistribution]
    validation_results: list[CollectorValidation]
    first_seen_at: str = ""
    last_seen_at: str = ""
    updated_at: str = ""


class CollectorDatabaseDatasetSearchResponse(BaseModel):
    search_id: UUID
    query: str
    origin: Literal["database"] = "database"
    items: list[CollectorCollectedDataset] = Field(default_factory=list)
    warnings: list[CollectorRepositorySearchWarning] = Field(default_factory=list)


class CollectorOnlineDatasetSearchResponse(BaseModel):
    search_id: UUID
    query: str
    origin: Literal["online"] = "online"
    items: list[CollectorRepositorySearchItem] = Field(default_factory=list)
    warnings: list[CollectorRepositorySearchWarning] = Field(default_factory=list)


class CollectorCollectionResponse(BaseModel):
    items: list[CollectorCollectedDataset]


class CollectorCollectionJobResponse(BaseModel):
    job: CollectorCollectionJob
