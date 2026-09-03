from __future__ import annotations

import pytest

from collector.classification.ensemble import EnsemblePageClassifier
from collector.classification.page import PageClassification, PageClassificationError
from collector.storage.models import DistributionCandidate, PageSnapshot


def test_ensemble_classifier_accepts_when_two_of_three_voters_accept():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _StaticClassifier(_classification(True))),
            ("llm_b", _StaticClassifier(_classification(False))),
            ("llm_c", _StaticClassifier(_classification(True))),
        ]
    )

    result = classifier.classify(_page(), [_distribution()])

    assert result.accepted is True

    ensemble = result.dataset_signals["ensemble"]
    assert ensemble["votes_required"] == 2
    assert ensemble["minimum_successful_votes"] == 2
    assert ensemble["successful_votes"] == 3
    assert ensemble["failed_votes"] == 0
    assert ensemble["accepted_votes"] == 2
    assert ensemble["decision"] == "accepted"
    assert ensemble["decision_reason"] == "enough_accept_votes"
    assert ensemble["decision_voter_ids"] == ["llm_a", "llm_c"]
    assert [vote["voter_id"] for vote in ensemble["voters"]] == [
        "llm_a",
        "llm_b",
        "llm_c",
    ]
    assert ensemble["voters"][0]["signals"] == {"reason": "dataset signal"}


def test_ensemble_classifier_uses_votes_not_probability_thresholds():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _StaticClassifier(_classification(True))),
            ("llm_b", _StaticClassifier(_classification(True))),
            ("llm_c", _StaticClassifier(_classification(False))),
        ]
    )

    result = classifier.classify(_page(), [_distribution()])

    assert result.accepted is True
    assert result.dataset_signals["ensemble"]["accepted_votes"] == 2
    assert result.dataset_signals["ensemble"]["decision_reason"] == "enough_accept_votes"


def test_ensemble_classifier_rejects_when_only_one_of_three_voters_accepts():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _StaticClassifier(_classification(True))),
            ("llm_b", _StaticClassifier(_classification(False))),
            ("llm_c", _StaticClassifier(_classification(False))),
        ]
    )

    result = classifier.classify(_page(), [_distribution()])

    assert result.accepted is False
    assert result.dataset_signals["ensemble"]["accepted_votes"] == 1
    assert result.dataset_signals["ensemble"]["successful_votes"] == 3
    assert result.dataset_signals["ensemble"]["decision_reason"] == "rejected_by_majority"


def test_ensemble_classifier_accepts_when_all_voters_accept():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _StaticClassifier(_classification(True))),
            ("llm_b", _StaticClassifier(_classification(True))),
            ("llm_c", _StaticClassifier(_classification(True))),
        ]
    )

    result = classifier.classify(_page(), [_distribution()])

    assert result.accepted is True
    assert result.dataset_signals["ensemble"]["accepted_votes"] == 3


def test_ensemble_classifier_accepts_with_one_failure_and_two_accepting_votes():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _FailingClassifier("timeout")),
            ("llm_b", _StaticClassifier(_classification(True))),
            ("llm_c", _StaticClassifier(_classification(True))),
        ]
    )

    result = classifier.classify(_page(), [_distribution()])

    assert result.accepted is True
    ensemble = result.dataset_signals["ensemble"]
    assert ensemble["successful_votes"] == 2
    assert ensemble["failed_votes"] == 1
    assert ensemble["accepted_votes"] == 2
    assert ensemble["decision_reason"] == "enough_accept_votes"
    assert ensemble["failures"] == [{"voter_id": "llm_a", "error": "timeout"}]


def test_ensemble_classifier_rejects_with_one_failure_one_accept_and_one_reject():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _FailingClassifier("timeout")),
            ("llm_b", _StaticClassifier(_classification(True))),
            ("llm_c", _StaticClassifier(_classification(False))),
        ]
    )

    result = classifier.classify(_page(), [_distribution()])

    assert result.accepted is False
    ensemble = result.dataset_signals["ensemble"]
    assert ensemble["successful_votes"] == 2
    assert ensemble["failed_votes"] == 1
    assert ensemble["accepted_votes"] == 1
    assert ensemble["decision"] == "rejected"
    assert ensemble["decision_reason"] == "insufficient_accept_votes"
    assert ensemble["decision_voter_ids"] == ["llm_c"]


def test_ensemble_classifier_raises_when_fewer_than_two_voters_succeed():
    classifier = EnsemblePageClassifier(
        [
            ("llm_a", _FailingClassifier("timeout")),
            ("llm_b", _FailingClassifier("bad response")),
            ("llm_c", _StaticClassifier(_classification(True))),
        ]
    )

    with pytest.raises(PageClassificationError, match="At least 2 classifier votes"):
        classifier.classify(_page(), [_distribution()])


def test_ensemble_classifier_rejects_duplicate_voter_ids():
    with pytest.raises(ValueError, match="voter ids must be unique"):
        EnsemblePageClassifier(
            [
                ("llm_a", _StaticClassifier(_classification(True))),
                ("llm_a", _StaticClassifier(_classification(True))),
            ]
        )


def test_ensemble_classifier_rejects_minimum_below_required_votes():
    voters = [
        ("llm_a", _StaticClassifier(_classification(True))),
        ("llm_b", _StaticClassifier(_classification(True))),
        ("llm_c", _StaticClassifier(_classification(True))),
    ]

    with pytest.raises(
        ValueError,
        match="minimum_successful_votes cannot be lower than votes_required",
    ):
        EnsemblePageClassifier(
            voters,
            votes_required=3,
            minimum_successful_votes=1,
        )


class _StaticClassifier:
    def __init__(self, classification: PageClassification) -> None:
        self._classification = classification

    def classify(self, page, distributions):
        return self._classification


class _FailingClassifier:
    def __init__(self, error: str) -> None:
        self._error = error

    def classify(self, page, distributions):
        raise PageClassificationError(self._error)


def _classification(accepted: bool) -> PageClassification:
    return PageClassification(
        accepted=accepted,
        dataset_signals={"reason": "dataset signal"},
    )


def _page() -> PageSnapshot:
    return PageSnapshot(
        url="https://example.org/datasets/mortality",
        canonical_url="https://example.org/datasets/mortality",
        title="Mortality health dataset",
        meta_description="Official mortality data.",
        text="Download CSV data for mortality indicators.",
    )


def _distribution() -> DistributionCandidate:
    return DistributionCandidate(
        url="https://example.org/files/mortality.csv",
        format="CSV",
        probability=0.95,
        anchor="Download CSV",
        mime_type="text/csv",
    )
