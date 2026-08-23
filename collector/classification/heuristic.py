from __future__ import annotations

from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.classification.page import PageClassification
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.storage.models import DistributionCandidate, PageSnapshot


class HeuristicPageClassifier:
    """Deterministic baseline classifier kept for tests and comparison runs."""

    def __init__(self, config: CollectorConfig = DEFAULT_CONFIG) -> None:
        self._config = config

    def classify(
        self,
        page: PageSnapshot,
        distributions: list[DistributionCandidate],
    ) -> PageClassification:
        dataset_score = score_dataset_page(page, distributions)
        health_score = score_health_page(page)
        accepted = (
            dataset_score.probability >= self._config.min_dataset_probability
            and health_score.probability >= self._config.min_health_probability
        )

        return PageClassification(
            accepted=accepted,
            dataset_probability=dataset_score.probability,
            dataset_signals=dataset_score.signals,
            health_probability=health_score.probability,
            health_label=health_score.label,
            health_signals=health_score.signals,
        )
