from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.discovery.adapters import DiscoveredPage
from collector.discovery.manager import discover_source
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import FetchedPage, fetch_public_html
from collector.storage.models import (
    CollectedDataset,
    DistributionCandidate,
    PageSnapshot,
    ValidationResult,
)
from collector.validation.downloads import validate_distribution

DiscoverFunction = Callable[[str], list[DiscoveredPage]]
FetchHTMLFunction = Callable[[str], FetchedPage]
ValidateDistributionFunction = Callable[[DistributionCandidate], ValidationResult]


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
        hosting_platform=page.hosting_platform,
        uploader=page.uploader,
        dataset_probability=dataset_score.probability,
        dataset_signals=dataset_score.signals,
        health_probability=health_score.probability,
        health_label=health_score.label,
        health_signals=health_score.signals,
        distributions=distributions,
    )


def collect_source(
    source_url: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    discover: DiscoverFunction = discover_source,
    fetch_html: FetchHTMLFunction = fetch_public_html,
    validate: ValidateDistributionFunction = validate_distribution,
) -> list[CollectedDataset]:
    collected_datasets: list[CollectedDataset] = []

    for discovered_page in discover(source_url)[: config.max_pages_per_source]:
        dataset = _collect_discovered_page(discovered_page, config, fetch_html, validate)
        if dataset is not None:
            collected_datasets.append(dataset)

    return collected_datasets


def _collect_discovered_page(
    discovered_page: DiscoveredPage,
    config: CollectorConfig,
    fetch_html: FetchHTMLFunction,
    validate: ValidateDistributionFunction,
) -> CollectedDataset | None:
    if _has_structured_discovery_metadata(discovered_page):
        dataset = analyze_discovered_page(discovered_page, config)
    else:
        try:
            fetched_page = fetch_html(discovered_page.url)
        except ValueError:
            return None

        dataset = analyze_html_page(fetched_page.final_url, fetched_page.html, config)
        if dataset is not None:
            dataset = replace(dataset, discovery_method=discovered_page.discovery_method)

    if dataset is None:
        return None

    return _with_valid_distributions(dataset, validate)


def analyze_discovered_page(
    discovered_page: DiscoveredPage,
    config: CollectorConfig = DEFAULT_CONFIG,
) -> CollectedDataset | None:
    page = PageSnapshot(
        url=discovered_page.url,
        canonical_url=discovered_page.url,
        title=discovered_page.title,
        h1=discovered_page.title,
        meta_description=discovered_page.description,
        publisher=discovered_page.publisher,
        text=" ".join(
            [
                discovered_page.title,
                discovered_page.description,
                discovered_page.publisher,
            ]
        ),
        json_ld=({"@type": "Dataset"},),
    )
    distributions = list(discovered_page.distributions)
    dataset_score = score_dataset_page(page, distributions)
    health_score = score_health_page(page)

    if (
        dataset_score.probability < config.min_dataset_probability
        or health_score.probability < config.min_health_probability
    ):
        return None

    return CollectedDataset(
        dataset_url=page.canonical_url,
        title=page.title or page.canonical_url,
        description=page.meta_description,
        publisher=page.publisher,
        hosting_platform="",
        uploader="",
        dataset_probability=dataset_score.probability,
        dataset_signals=dataset_score.signals,
        health_probability=health_score.probability,
        health_label=health_score.label,
        health_signals=health_score.signals,
        distributions=distributions,
        discovery_method=discovered_page.discovery_method,
    )


def _has_structured_discovery_metadata(discovered_page: DiscoveredPage) -> bool:
    return bool(
        discovered_page.title
        or discovered_page.description
        or discovered_page.publisher
        or discovered_page.distributions
    )


def _with_valid_distributions(
    dataset: CollectedDataset,
    validate: ValidateDistributionFunction,
) -> CollectedDataset | None:
    valid_distributions: list[DistributionCandidate] = []
    validation_results: list[ValidationResult] = []

    for distribution in dataset.distributions:
        validation_result = validate(distribution)
        if not validation_result.ok:
            continue

        valid_distributions.append(distribution)
        validation_results.append(validation_result)

    if not valid_distributions:
        return None

    return replace(
        dataset,
        distributions=valid_distributions,
        validation_results=validation_results,
    )
