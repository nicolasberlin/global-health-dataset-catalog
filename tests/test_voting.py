from __future__ import annotations

from threading import Barrier, Event

import pytest

from collector.classification.ensemble import (
    EnsemblePageClassifier,
    EnsembleRepositoryRelevanceClassifier,
)
from collector.classification.page import PageClassification, PageClassificationError
from collector.classification.repository import RepositoryClassification
from collector.classification.voting import run_voters
from collector.storage.models import PageSnapshot


class _Classifier:
    def __init__(self, callback):
        self.callback = callback

    def classify(self, *args):
        return self.callback()


def _classification(kind, reason="match"):
    if kind == "page":
        return PageClassification(accepted=True, dataset_signals={"reason": reason})
    return RepositoryClassification(relevance_label="relevant", reason=reason)


def _classify(kind, voters):
    page = PageSnapshot(
        url="https://example.org/dataset",
        canonical_url="https://example.org/dataset",
    )
    if kind == "page":
        result = EnsemblePageClassifier(voters).classify(page, [])
        return result, result.dataset_signals["ensemble"]
    result = EnsembleRepositoryRelevanceClassifier(voters).classify(page)
    return result, result.ensemble


@pytest.mark.parametrize("kind", ["page", "repository"])
def test_voters_run_concurrently_but_keep_configured_order(kind):
    started = Barrier(3, timeout=5)
    finished = [Event() for _ in range(3)]
    completion_order = []

    def callback(index):
        def classify():
            started.wait()
            if index < 2:
                assert finished[index + 1].wait(timeout=5)
            completion_order.append(index)
            finished[index].set()
            return _classification(kind, reason=f"reason {index}")
        return classify

    voters = [(f"voter_{i}", _Classifier(callback(i))) for i in range(3)]
    result, summary = _classify(kind, voters)

    assert completion_order == [2, 1, 0]
    assert result.accepted is True
    assert [vote["voter_id"] for vote in summary["voters"]] == [
        "voter_0", "voter_1", "voter_2",
    ]
    assert summary["decision_voter_ids"] == ["voter_0", "voter_1", "voter_2"]
    if kind == "repository":
        assert result.reason == "reason 0"


@pytest.mark.parametrize("kind", ["page", "repository"])
@pytest.mark.parametrize("error_type", [PageClassificationError, ValueError, RuntimeError])
def test_ensembles_preserve_their_expected_error_policy(kind, error_type):
    def fail():
        raise error_type("invalid response")

    voters = [
        ("failed", _Classifier(fail)),
        ("second", _Classifier(lambda: _classification(kind))),
        ("third", _Classifier(lambda: _classification(kind))),
    ]
    handled = error_type is PageClassificationError or (
        kind == "repository" and error_type is ValueError
    )
    if not handled:
        with pytest.raises(error_type, match="invalid response"):
            _classify(kind, voters)
        return

    result, summary = _classify(kind, voters)
    assert result.accepted is True
    assert summary["successful_votes"] == 2
    assert summary["failed_votes"] == 1
    assert summary["failures"] == [{"voter_id": "failed", "error": "invalid response"}]


def test_vote_construction_errors_are_not_swallowed():
    def invalid_vote(voter_id, classification):
        raise ValueError("vote construction bug")

    with pytest.raises(ValueError, match="vote construction bug"):
        run_voters(
            [("voter", object())],
            classify=lambda classifier: True,
            make_vote=invalid_vote,
            handled_errors=(ValueError,),
        )


def test_repository_rejection_tie_uses_conservative_label():
    voters = [
        ("relevant", _Classifier(lambda: RepositoryClassification("relevant", "match"))),
        ("negative", _Classifier(lambda: RepositoryClassification("not_relevant", "mismatch"))),
        ("uncertain", _Classifier(lambda: RepositoryClassification(
            "insufficient_information", "missing geography", ["geography"],
        ))),
    ]
    result, summary = _classify("repository", voters)

    assert result.accepted is False
    assert result.relevance_label == "not_relevant"
    assert result.reason == "mismatch"
    assert result.missing_information == []
    assert summary["decision_voter_ids"] == ["negative", "uncertain"]
