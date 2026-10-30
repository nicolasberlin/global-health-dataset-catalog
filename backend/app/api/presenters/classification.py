"""Present classification decisions and filter internal model failure details."""

from __future__ import annotations

from typing import Any

from app.api.schemas.classification import CollectorRepositoryClassification
from collector.diagnostics import Diagnostic, public_diagnostics


def _public_ensemble(ensemble: dict[str, Any]) -> dict[str, Any]:
    """Preserve decisions and votes while replacing technical failure details."""

    if "failures" not in ensemble:
        return dict(ensemble)
    return {
        **ensemble,
        "failures": [
            {
                "voter_id": failure["voter_id"],
                "error": "Classifier vote failed.",
                "error_code": "classifier_vote_failed",
                "errors": public_diagnostics(
                    failure.get("errors")
                    or [
                        Diagnostic(
                            "legacy_unknown", "classification", voter_id=failure["voter_id"]
                        ).to_dict(),
                    ]
                ),
            }
            for failure in ensemble["failures"]
        ],
    }


def public_repository_classification(
    classification: dict[str, Any] | None,
) -> CollectorRepositoryClassification | None:
    """Prepare a candidate's saved classification, filtering internal vote failures."""
    if classification is None:
        return None
    return CollectorRepositoryClassification(
        **{**classification, "ensemble": _public_ensemble(classification["ensemble"])},
    )


def public_dataset_signals(signals: dict[str, Any]) -> dict[str, Any]:
    """Copy a dataset's classification signals with client-safe model failures."""
    if "ensemble" not in signals:
        return dict(signals)
    return {**signals, "ensemble": _public_ensemble(signals["ensemble"])}
