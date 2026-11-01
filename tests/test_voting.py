from __future__ import annotations

from dataclasses import dataclass
from threading import Barrier, Event

import pytest

from collector.classification.relevance.ensemble import EnsembleRepositoryRelevanceClassifier
from collector.classification.relevance.models import RepositoryClassification
from collector.collection.eligibility.ensemble import EnsemblePageClassifier
from collector.collection.eligibility.models import PageClassification
from collector.llm.errors import ClassificationError
from collector.llm.voting import VotingEnsemble, run_voters
from collector.models import PageSnapshot


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
@pytest.mark.parametrize("error_type", [ClassificationError, ValueError, RuntimeError])
def test_ensembles_preserve_their_expected_error_policy(kind, error_type):
    def fail():
        raise error_type("invalid response")

    voters = [
        ("failed", _Classifier(fail)),
        ("second", _Classifier(lambda: _classification(kind))),
        ("third", _Classifier(lambda: _classification(kind))),
    ]
    handled = error_type is ClassificationError or (
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
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["voter_id"] == "failed"
    assert summary["failures"][0]["error"] == "invalid response"
    assert summary["failures"][0]["errors"][0]["code"] == "processing_failed"


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


def test_cancelled_ensemble_cannot_start_a_new_model_invocation():
    from unittest.mock import Mock

    from collector.execution import ExecutionControl, ExecutionStopped, execution_control

    control = ExecutionControl()
    control.abort()
    token = execution_control.set(control)
    classify = Mock()
    try:
        with pytest.raises(ExecutionStopped):
            run_voters(
                [("a", object()), ("b", object())], classify=classify,
                make_vote=lambda voter, decision: decision, handled_errors=(ValueError,),
            )
    finally:
        execution_control.reset(token)
    classify.assert_not_called()


@dataclass(frozen=True)
class _AcceptanceVote:
    voter_id: str
    accepted: bool


@pytest.mark.parametrize(
    "decisions, minimum_accept_votes, minimum_successful_votes, accepted, reason, supporting",
    [
        ([True, False, True], 2, 3, True, "enough_accept_votes", ["0", "2"]),
        ([True, False, False], 2, 3, False, "rejected_by_majority", ["1", "2"]),
        ([True, False], 2, 2, False, "insufficient_accept_votes", ["1"]),
        ([False, False, True], 3, 3, False, "insufficient_accept_votes", ["0", "1"]),
        ([False], 1, 1, False, "rejected_by_majority", ["0"]),
        ([True], 1, None, True, "enough_accept_votes", ["0"]),
    ],
)
def test_shared_ensemble_preserves_threshold_decisions_and_summary_contract(
    decisions, minimum_accept_votes, minimum_successful_votes, accepted, reason, supporting,
):
    ensemble = VotingEnsemble(
        [(str(index), decision) for index, decision in enumerate(decisions)],
        minimum_accept_votes=minimum_accept_votes,
        minimum_successful_votes=minimum_successful_votes,
    )
    result = ensemble.evaluate(
        classify=lambda decision: decision,
        make_vote=_AcceptanceVote,
        handled_errors=(ClassificationError,),
    )

    assert result.accepted is accepted
    assert result.decision_reason == reason
    assert [vote.voter_id for vote in result.supporting_votes] == supporting
    summary = result.to_summary(
        lambda vote: {"voter_id": vote.voter_id, "accepted": vote.accepted},
    )
    assert summary == {
        "votes_required": minimum_accept_votes,
        "minimum_successful_votes": minimum_successful_votes or minimum_accept_votes,
        "successful_votes": len(decisions),
        "failed_votes": 0,
        "accepted_votes": sum(decisions),
        "decision": "accepted" if accepted else "rejected",
        "decision_reason": reason,
        "decision_voter_ids": supporting,
        "voters": [
            {"voter_id": str(index), "accepted": decision}
            for index, decision in enumerate(decisions)
        ],
        "failures": [],
    }


def test_shared_ensemble_preserves_incomplete_vote_errors_and_diagnostic_order():
    def classify(value):
        if isinstance(value, Exception):
            raise value
        return value

    ensemble = VotingEnsemble(
        [
            ("good", True),
            ("timeout", ClassificationError("timed out", code="llm_timeout")),
            ("invalid", ClassificationError("bad JSON", code="llm_invalid_response")),
        ],
        minimum_accept_votes=2,
        minimum_successful_votes=3,
    )
    with pytest.raises(ClassificationError) as caught:
        ensemble.evaluate(
            classify=classify,
            make_vote=_AcceptanceVote,
            handled_errors=(ClassificationError,),
        )

    assert str(caught.value) == (
        "At least 3 classifier votes are required; 1 succeeded. "
        "Failures: timeout: timed out; invalid: bad JSON"
    )
    assert [(item.code, item.voter_id) for item in caught.value.diagnostics] == [
        ("llm_timeout", "timeout"), ("llm_invalid_response", "invalid"),
    ]
