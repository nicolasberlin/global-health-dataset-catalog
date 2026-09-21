"""Discover, classify, and validate datasets without persisting them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from urllib.parse import urlsplit

from collector.classification.factory import build_default_page_classifier
from collector.classification.page import PageClassifier
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.discovery.adapters import DiscoveredPage
from collector.discovery.adapters.shared import EXCLUDED_RESOURCE_FORMATS
from collector.discovery.manager import discover_source
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import FetchedPage, fetch_public_html
from collector.storage.metadata import metadata_evidence
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
    *,
    discovered_page: DiscoveredPage | None = None,
) -> CollectedDataset | None:
    """Extract and classify one HTML page before distribution validation.

    A valid rejection returns ``None``. Classifier failures, including an
    unavailable default EPFL RCP voter, propagate as errors rather than being
    counted as rejected pages. This function performs no persistence.
    """

    page = extract_page(url, html)
    evidence = metadata_evidence(page, kind="page", source_url=page.url)
    if discovered_page is not None:
        page = _merge_discovery_metadata(page, discovered_page)
        for field in ("date_of_publication", "sharing_license"):
            value = getattr(discovered_page, field)
            if value:
                evidence.setdefault(field, []).append({
                    "value": value, "kind": "adapter", "source_url": discovered_page.url,
                })
    distributions = [item for item in extract_distributions(page) if _usable_distribution(item)]
    if not distributions:
        return None
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
        date_of_publication=page.date_of_publication,
        sharing_license=page.sharing_license,
        doi=page.doi,
        metadata_provenance=evidence,
        dataset_signals=classification.dataset_signals,
        distributions=distributions,
    )


def collect_source_with_report(
    source_url: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    discover: DiscoverFunction = discover_source,
    fetch_html: FetchHTMLFunction | None = None,
    validate: ValidateDistributionFunction | None = None,
    classifier: PageClassifier | None = None,
) -> CollectionResult:
    """Collect a bounded source into datasets and an audit report.

    Discovery, HTML fetching, classification, and distribution probes may
    perform outbound requests. At most ``max_pages_per_source`` candidates are
    analyzed and at most ``max_distribution_attempts`` distinct resources per
    accepted page are probed, retaining up to ``max_distributions_saved``.
    A page enters the result only after classifier
    acceptance and at least one successful distribution validation.

    The returned result is not saved here. Fetch, classifier, and validation
    errors propagate to the caller instead of being counted as rejections.

    Default fetch and validation functions use this run's network settings.
    Explicitly supplied functions retain their single-argument interface and
    are responsible for their own network settings.
    """

    if fetch_html is None:
        fetch_html = partial(
            fetch_public_html,
            timeout=config.request_timeout_seconds,
            user_agent=config.user_agent,
        )
    if validate is None:
        validate = partial(
            validate_distribution,
            timeout=config.request_timeout_seconds,
            max_sample_bytes=config.max_sample_bytes,
        )

    collected_datasets: list[CollectedDataset] = []
    validation_failures: list[ValidationResult] = []

    def validate_and_record(distribution: DistributionCandidate) -> ValidationResult:
        result = validate(distribution)
        if not result.ok:
            validation_failures.append(result)
        return result

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
            validate_and_record,
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
            validation_failures=validation_failures,
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


def collect_repository_candidate_with_report(
    candidate_url: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    fetch_html: FetchHTMLFunction | None = None,
    validate: ValidateDistributionFunction | None = None,
    classifier: PageClassifier | None = None,
) -> CollectionResult:
    """Collect one repository landing page through the normal validation gates.

    Repository candidates are individual records, so this wrapper prevents the
    generic discovery adapter from replacing that URL with an entire site
    sitemap. Provider metadata is deliberately not passed into collection.
    """

    normalized_url = normalize_http_url(candidate_url)
    if normalized_url is None:
        raise ValueError("Repository candidate URL must be a valid HTTP(S) URL.")

    def discover_candidate(_: str) -> list[DiscoveredPage]:
        return [
            DiscoveredPage(
                url=normalized_url,
                discovery_method="repository_search",
                priority=1.0,
            )
        ]

    return collect_source_with_report(
        normalized_url,
        config=config,
        discover=discover_candidate,
        fetch_html=fetch_html,
        validate=validate,
        classifier=classifier,
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
    # A title alone cannot replace the page containing the download links.
    if any(_usable_distribution(item) for item in discovered_page.distributions):
        dataset = analyze_discovered_page(discovered_page, config, page_classifier)
    else:
        catalog_url = discovered_page.discovery_metadata.get("data_json_url")
        if isinstance(catalog_url, str) and (
            urlsplit(discovered_page.url)[:3] == urlsplit(catalog_url)[:3]
        ):
            # data.json can synthesize record URLs on the catalog itself.
            return None, 0
        fetched_page = fetch_html(discovered_page.url)
        mime_type = fetched_page.content_type.split(";", 1)[0].strip().lower()
        if mime_type and mime_type not in {"text/html", "application/xhtml+xml"}:
            return None, 0
        dataset = analyze_html_page(
            fetched_page.final_url,
            fetched_page.html,
            config,
            page_classifier,
            discovered_page=discovered_page,
        )
        if dataset is not None:
            dataset = replace(
                dataset,
                discovery_method=discovered_page.discovery_method,
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
    distributions = [item for item in discovered_page.distributions if _usable_distribution(item)]
    if not distributions:
        return None
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
        date_of_publication=page.date_of_publication,
        sharing_license=page.sharing_license,
        doi=page.doi,
        metadata_provenance=metadata_evidence(
            page, kind="adapter", source_url=page.url,
        ),
        dataset_signals=classification.dataset_signals,
        distributions=distributions,
        discovery_method=discovered_page.discovery_method,
    )


def _classifier_or_default(
    classifier: PageClassifier | None,
) -> PageClassifier:
    return classifier if classifier is not None else build_default_page_classifier()


def _usable_distribution(distribution: DistributionCandidate) -> bool:
    """Recognize plausible data links; network validation still decides availability."""
    return (
        normalize_http_url(distribution.url) is not None
        and distribution.format.upper() not in EXCLUDED_RESOURCE_FORMATS
        and "html" not in distribution.mime_type.lower()
    )


def _merge_discovery_metadata(page: PageSnapshot, discovered: DiscoveredPage) -> PageSnapshot:
    """Fill missing page fields before classification, retaining the extracted links."""
    fields = (
        "title", "publisher", "geography", "date_of_publication", "diseases",
        "size_of_dataset", "demographic_information", "sharing_license", "modality_of_data",
    )
    return replace(
        page,
        **{field: getattr(page, field) or getattr(discovered, field) for field in fields},
        meta_description=page.meta_description or page.og_description or discovered.description,
        description_of_dataset=page.description_of_dataset or discovered.description,
        text=" ".join((page.text, discovered.title, discovered.description, discovered.publisher)),
    )


def _with_valid_distributions_and_report(
    dataset: CollectedDataset,
    config: CollectorConfig,
    validate: ValidateDistributionFunction,
) -> tuple[CollectedDataset | None, int]:
    """Keep bounded, successfully probed distributions or reject the dataset."""

    valid_distributions: list[DistributionCandidate] = []
    validation_results: list[ValidationResult] = []
    validated_keys: set[tuple[str, str]] = set()
    attempted_urls: set[str] = set()
    invalid_count = 0

    ranked_distributions = sorted(
        dataset.distributions, key=lambda item: item.probability, reverse=True,
    )
    for distribution in ranked_distributions:
        if (len(attempted_urls) >= config.max_distribution_attempts
                or len(valid_distributions) >= config.max_distributions_saved):
            break
        url = normalize_http_url(distribution.url)
        if url is None or url in attempted_urls:
            continue
        attempted_urls.add(url)
        validation_result = validate(distribution)
        if not validation_result.ok:
            invalid_count += 1
            continue

        # Persistence pairs a distribution and its validation by URL and format.
        # Keep the verified format when headers or sampled bytes refine the guess.
        validated_distribution = replace(distribution, format=validation_result.format)
        key = (validated_distribution.url, validated_distribution.format)
        if key in validated_keys:
            continue
        validated_keys.add(key)
        valid_distributions.append(validated_distribution)
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
