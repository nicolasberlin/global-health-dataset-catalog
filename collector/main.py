from __future__ import annotations

from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.storage.models import CollectedDataset


def analyze_html_page(
    url: str,
    html: str,
    config: CollectorConfig = DEFAULT_CONFIG,
) -> CollectedDataset | None:
    page = extract_page(url, html)
    distributions = extract_distributions(page)
    dataset_score = score_dataset_page(page, distributions)
    health_score = score_health_page(page)

    if (
        dataset_score.probability < config.min_dataset_probability
        or health_score.probability < config.min_health_probability
    ):
        return None

    return CollectedDataset(
        dataset_url=page.canonical_url,
        title=page.title or page.h1 or page.canonical_url,
        description=page.meta_description or page.og_description,
        publisher=page.publisher,
        dataset_probability=dataset_score.probability,
        dataset_signals=dataset_score.signals,
        health_probability=health_score.probability,
        health_label=health_score.label,
        health_signals=health_score.signals,
        distributions=distributions,
    )

