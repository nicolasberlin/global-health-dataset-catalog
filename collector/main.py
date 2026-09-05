"""Discover, classify, and validate datasets without persisting them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from collector.classification.factory import build_default_page_classifier
from collector.classification.page import PageClassifier
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.discovery.adapters import DiscoveredPage
from collector.discovery.manager import discover_source
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import FetchedPage, fetch_public_html
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    PageSnapshot,
    ValidationResult,
)
from collector.url_utils import normalize_http_url
from collector.validation.downloads import validate_distribution

DiscoverFunction = Callable[[str], list[DiscoveredPage]]
FetchHTMLFunction = Callable[[str], FetchedPage]
ValidateDistributionFunction = Callable[[DistributionCandidate], ValidationResult]


def analyze_html_page(
    url: str,
    html: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    classifier: PageClassifier | None = None,
) -> CollectedDataset | None:
    """Extract and classify one HTML page before distribution validation.

    A valid rejection returns ``None``. Classifier failures, including an
    unavailable default EPFL RCP voter, propagate as errors rather than being
    counted as rejected pages. This function performs no persistence.
    """

    page = extract_page(url, html)
    distributions = extract_distributions(page)
    page_classifier = _classifier_or_default(classifier)
    classification = page_classifier.classify(page, distributions)

    if not classification.accepted:
        return None

    return CollectedDataset(
        dataset_url=page.dataset_url,
        title=page.title or page.h1 or page.canonical_url,
        description=page.meta_description or page.og_description,
        publisher=page.publisher,
        hosting_platform=page.hosting_platform,
        uploader=page.uploader,
        geography=page.geography,
        dataset_signals=classification.dataset_signals,
        distributions=distributions,
    )


def collect_source_with_report(
    source_url: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    discover: DiscoverFunction = discover_source,
    fetch_html: FetchHTMLFunction = fetch_public_html,
    validate: ValidateDistributionFunction = validate_distribution,
    classifier: PageClassifier | None = None,
) -> CollectionResult:
    """Collect a bounded source into datasets and an audit report.

    Discovery, HTML fetching, classification, and distribution probes may
    perform outbound requests. At most ``max_pages_per_source`` candidates are
    analyzed and at most ``max_distributions_per_dataset`` resources per
    accepted page are probed. A page enters the result only after classifier
    acceptance and at least one successful distribution validation.

    The returned result is not saved here. Classifier or validation errors
    propagate to the caller; an HTML fetch reported as ``ValueError`` is
    treated as a rejected candidate.
    """

    collected_datasets: list[CollectedDataset] = []
    rejected_count = 0
    invalid_distribution_count = 0
    discovered_pages = discover(source_url)
    # Keep the full discovery count for reporting while bounding costly page
    # fetches and LLM calls to the configured analysis limit.
    selected_pages = discovered_pages[: config.max_pages_per_source]
    page_classifier = _classifier_or_default(classifier)

    for discovered_page in selected_pages:
        dataset, invalid_count = _collect_discovered_page_with_report(
            discovered_page,
            config,
            fetch_html,
            validate,
            page_classifier,
        )
        invalid_distribution_count += invalid_count
        if dataset is not None:
            collected_datasets.append(dataset)
        else:
            rejected_count += 1

    return CollectionResult(
        datasets=collected_datasets,
        report=CollectionReport(
            discovered_count=len(discovered_pages),
            analyzed_count=len(selected_pages),
            accepted_count=len(collected_datasets),
            rejected_count=rejected_count,
            invalid_distribution_count=invalid_distribution_count,
            discovery_methods=tuple(
                sorted(
                    {
                        page.discovery_method
                        for page in discovered_pages
                        if page.discovery_method
                    }
                )
            ),
        ),
    )


def _collect_discovered_page_with_report(
    discovered_page: DiscoveredPage,
    config: CollectorConfig,
    fetch_html: FetchHTMLFunction,
    validate: ValidateDistributionFunction,
    classifier: PageClassifier | None = None,
) -> tuple[CollectedDataset | None, int]:
    """Turn one discovery candidate into a validated transient dataset."""

    page_classifier = _classifier_or_default(classifier)
    # Structured adapters already provide classifier evidence, so fetching the
    # landing page again would add network cost without being required.
    if _has_structured_discovery_metadata(discovered_page):
        dataset = analyze_discovered_page(discovered_page, config, page_classifier)
    else:
        try:
            fetched_page = fetch_html(discovered_page.url)
        except ValueError:
            # An inaccessible landing page is a candidate rejection; other
            # failures remain exceptional and abort the collection run.
            return None, 0

        dataset = analyze_html_page(
            fetched_page.final_url,
            fetched_page.html,
            config,
            page_classifier,
        )
        if dataset is not None:
            dataset = replace(
                dataset,
                discovery_method=discovered_page.discovery_method,
                geography=(
                    dataset.geography or discovered_page.geography
                ),
            )

    if dataset is None:
        return None, 0

    return _with_valid_distributions_and_report(dataset, config, validate)


def analyze_discovered_page(
    discovered_page: DiscoveredPage,
    config: CollectorConfig = DEFAULT_CONFIG,
    classifier: PageClassifier | None = None,
) -> CollectedDataset | None:
    """Classify structured adapter metadata without fetching its landing page.

    The returned dataset is still transient and its distribution candidates
    must pass validation before the collection result can contain it.
    """

    dataset_url = normalize_http_url(discovered_page.url)
    if dataset_url is None:
        return None

    page = PageSnapshot(
        url=dataset_url,
        canonical_url=dataset_url,
        title=discovered_page.title,
        h1=discovered_page.title,
        meta_description=discovered_page.description,
        publisher=discovered_page.publisher,
        geography=discovered_page.geography,
        date_of_publication=discovered_page.date_of_publication,
        dataset_url=dataset_url,
        diseases=discovered_page.diseases,
        size_of_dataset=discovered_page.size_of_dataset,
        demographic_information=discovered_page.demographic_information,
        sharing_license=discovered_page.sharing_license,
        modality_of_data=discovered_page.modality_of_data,
        description_of_dataset=discovered_page.description,
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
    page_classifier = _classifier_or_default(classifier)
    classification = page_classifier.classify(page, distributions)

    if not classification.accepted:
        return None

    return CollectedDataset(
        dataset_url=page.dataset_url,
        title=page.title or page.canonical_url,
        description=page.meta_description,
        publisher=page.publisher,
        hosting_platform="",
        uploader="",
        geography=page.geography,
        dataset_signals=classification.dataset_signals,
        distributions=distributions,
        discovery_method=discovered_page.discovery_method,
    )


def _classifier_or_default(
    classifier: PageClassifier | None,
) -> PageClassifier:
    return classifier if classifier is not None else build_default_page_classifier()


def _has_structured_discovery_metadata(discovered_page: DiscoveredPage) -> bool:
    """Return whether adapter evidence is sufficient to skip an HTML fetch."""

    return bool(
        discovered_page.title
        or discovered_page.description
        or discovered_page.publisher
        or discovered_page.distributions
    )


def _with_valid_distributions_and_report(
    dataset: CollectedDataset,
    config: CollectorConfig,
    validate: ValidateDistributionFunction,
) -> tuple[CollectedDataset | None, int]:
    """Keep bounded, successfully probed distributions or reject the dataset."""

    valid_distributions: list[DistributionCandidate] = []
    validation_results: list[ValidationResult] = []
    invalid_count = 0

    # Classification sees extracted candidates first; this separate limit
    # bounds network probes and the distributions eligible for persistence.
    for distribution in dataset.distributions[: config.max_distributions_per_dataset]:
        validation_result = validate(distribution)
        if not validation_result.ok:
            invalid_count += 1
            continue

        valid_distributions.append(distribution)
        validation_results.append(validation_result)

    if not valid_distributions:
        return None, invalid_count

    return (
        replace(
            dataset,
            distributions=valid_distributions,
            validation_results=validation_results,
        ),
        invalid_count,
    )
