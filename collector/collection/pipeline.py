"""Shared extraction and classification, independent of the selected connector."""

from __future__ import annotations

from dataclasses import replace

from collector.classification.page import PageClassifier
from collector.collection.contracts import StrategyResult
from collector.collection.records import NormalizedRecord
from collector.config import CollectorConfig
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.storage.models import CollectedDataset, DistributionCandidate


def eligible_resources(resolved: StrategyResult) -> list[DistributionCandidate]:
    from collector.main import _usable_distribution

    resources = list(resolved.page.distributions)
    if resolved.html:
        resources = extract_distributions(extract_page(resolved.page.url, resolved.html))
    return [resource for resource in resources if _usable_distribution(resource)]


def classify_resolution(
    resolved: StrategyResult,
    resources: list[DistributionCandidate],
    config: CollectorConfig,
    classifier: PageClassifier | None,
    *, record_url: str | None = None,
    known_record: NormalizedRecord | None = None,
    record_identity: dict[str, str] | None = None,
) -> CollectedDataset | None:
    # Keep existing public collection entry points while avoiding an import cycle.
    from collector.main import analyze_discovered_page, analyze_html_page

    if resolved.html:
        from collector.collection.compatibility import to_strategy_result

        return analyze_html_page(
            resolved.page.url, resolved.html, config, classifier,
            distribution_candidates=resources, record_url=record_url,
            record_identity=record_identity,
            discovered_page=to_strategy_result(known_record, resolved.page.discovery_method).page
            if known_record else None,
        )
    return analyze_discovered_page(
        replace(resolved.page, distributions=tuple(resources)), config, classifier,
    )

