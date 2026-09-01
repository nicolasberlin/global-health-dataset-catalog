from __future__ import annotations

import pytest

from collector.classification.ensemble import EnsembleRepositoryRelevanceClassifier
from collector.classification.page import PageClassificationError
from collector.classification.repository import RepositoryClassification
from collector.storage.models import PageSnapshot


def test_repository_ensemble_accepts_by_majority():
    classifier = EnsembleRepositoryRelevanceClassifier(
        [
            ("llm_a", _StaticClassifier(_classification("relevant", "clear match"))),
            (
                "llm_b",
                _StaticClassifier(
                    _classification("somewhat_relevant", "partial match")
                ),
            ),
            (
                "llm_c",
                _StaticClassifier(
                    _classification("not_relevant", "different topic")
                ),
            ),
        ]
    )

    result = classifier.classify(_page())

    assert result.accepted is True
    assert result.relevance_label == "somewhat_relevant"
    assert result.reason == "partial match"

    ensemble = result.ensemble
    assert ensemble["accepted_votes"] == 2
    assert ensemble["decision"] == "accepted"
    assert ensemble["decision_reason"] == "enough_accept_votes"
    assert ensemble["decision_voter_ids"] == ["llm_a", "llm_b"]


def test_repository_ensemble_rejects_with_one_failure_and_one_accepting_vote():
    classifier = EnsembleRepositoryRelevanceClassifier(
        [
            ("llm_a", _FailingClassifier("timeout")),
            ("llm_b", _StaticClassifier(_classification("relevant", "match"))),
            (
                "llm_c",
                _StaticClassifier(
                    _classification(
                        "insufficient_information",
                        "geography is missing",
                        ["geography"],
                    )
                ),
            ),
        ]
    )

    result = classifier.classify(_page())

    assert result.accepted is False
    assert result.relevance_label == "insufficient_information"
    assert result.missing_information == ["geography"]
    assert result.ensemble["successful_votes"] == 2
    assert result.ensemble["failed_votes"] == 1
    assert result.ensemble["decision_reason"] == "insufficient_accept_votes"


def test_repository_ensemble_raises_when_fewer_than_two_voters_succeed():
    classifier = EnsembleRepositoryRelevanceClassifier(
        [
            ("llm_a", _FailingClassifier("timeout")),
            ("llm_b", _FailingClassifier("bad response")),
            ("llm_c", _StaticClassifier(_classification("relevant", "match"))),
        ]
    )

    with pytest.raises(PageClassificationError, match="At least 2 classifier votes"):
        classifier.classify(_page())


def test_repository_classification_derives_acceptance_from_relevance_label():
    assert _classification("relevant", "match").accepted is True
    assert _classification("somewhat_relevant", "partial match").accepted is True
    assert _classification("not_relevant", "mismatch").accepted is False
    assert (
        _classification(
            "insufficient_information",
            "geography is missing",
            ["geography"],
        ).accepted
        is False
    )


def test_repository_classification_requires_missing_information_details():
    with pytest.raises(ValueError, match="identify missing information"):
        _classification("insufficient_information", "geography is missing")


class _StaticClassifier:
    def __init__(self, classification: RepositoryClassification) -> None:
        self._classification = classification

    def classify(self, page):
        return self._classification


class _FailingClassifier:
    def __init__(self, error: str) -> None:
        self._error = error

    def classify(self, page):
        raise PageClassificationError(self._error)


def _classification(
    relevance_label,
    reason: str,
    missing_information: list[str] | None = None,
) -> RepositoryClassification:
    return RepositoryClassification(
        relevance_label=relevance_label,
        reason=reason,
        missing_information=missing_information or [],
    )


def _page() -> PageSnapshot:
    return PageSnapshot(
        url="https://example.org/datasets/mortality",
        canonical_url="https://example.org/datasets/mortality",
        search_query="malaria mortality",
        title="Mortality health dataset",
        meta_description="Official mortality data.",
        text="Download CSV data for mortality indicators.",
    )
