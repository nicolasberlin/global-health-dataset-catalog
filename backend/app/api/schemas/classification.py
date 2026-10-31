"""Classification decisions, ensemble votes and vote progress exposed by the API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import ProcessingDiagnosticView
from collector.classification.repository import (
    MAX_REPOSITORY_CLASSIFICATION_REASON_CHARS,
    MAX_REPOSITORY_MISSING_INFORMATION_CHARS,
    MAX_REPOSITORY_MISSING_INFORMATION_ITEMS,
    REPOSITORY_ACCEPTED_RELEVANCE_LABELS,
    RepositoryRelevanceLabel,
)

RepositoryMissingInformation = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REPOSITORY_MISSING_INFORMATION_CHARS),
]


RepositoryVoterId = Annotated[str, Field(min_length=1, max_length=100)]


class ClassificationVoteView(BaseModel):
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
    def validate_decision(self) -> ClassificationVoteView:
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


class ClassificationVoteFailureView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voter_id: RepositoryVoterId
    error: str = Field(min_length=1, max_length=2_000)
    error_code: Literal["classifier_vote_failed"] = "classifier_vote_failed"
    errors: list[ProcessingDiagnosticView] = Field(default_factory=list)


class ClassificationEnsembleView(BaseModel):
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
    voters: list[ClassificationVoteView] = Field(
        default_factory=list,
        max_length=10,
    )
    failures: list[ClassificationVoteFailureView] = Field(
        default_factory=list,
        max_length=10,
    )


class CandidateClassificationView(BaseModel):
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
    ensemble: ClassificationEnsembleView

    @model_validator(mode="after")
    def validate_decision(self) -> CandidateClassificationView:
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


class VoteProgressView(BaseModel):
    total: int = Field(default=0, ge=0, le=10)
    succeeded: int = Field(default=0, ge=0, le=10)
    failed: int = Field(default=0, ge=0, le=10)
