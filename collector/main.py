"""Discover, classify, and validate datasets without persisting them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from urllib.parse import urlsplit

from collector.budget import CollectionBudgetExceeded, check_collection_budget, collection_budget
from collector.classification.page import PageClassifier
from collector.collection.pipeline import (
    _classifier_or_default,
    _usable_distribution,
)
from collector.collection.pipeline import (
    analyze_discovered_page as analyze_discovered_page,
)
from collector.collection.pipeline import (
    analyze_html_page as analyze_html_page,
)
from collector.collection.resources import ResourceCheckState, retain_validated_resources
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.diagnostics import Diagnostic
from collector.discovery.adapters import DiscoveredPage
from collector.discovery.manager import discover_source
from collector.extraction.errors import ExtractionError
from collector.fetch import FetchedPage, PageFetchError, fetch_public_html
from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    CollectionResult,
    DistributionCandidate,
    ValidationResult,
)
from collector.url_utils import normalize_http_url
from collector.validation.downloads import validate_distribution

DiscoverFunction = Callable[[str], list[DiscoveredPage]]
FetchHTMLFunction = Callable[[str], FetchedPage]
ValidateDistributionFunction = Callable[[DistributionCandidate], ValidationResult]


def collect_source_with_report(
    source_url: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    discover: DiscoverFunction | None = None,
    fetch_html: FetchHTMLFunction | None = None,
    validate: ValidateDistributionFunction | None = None,
    classifier: PageClassifier | None = None,
    *,
    browser=None,
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

    Default discovery, fetch and validation functions use this run's network settings.
    Explicitly supplied functions retain their single-argument interface and
    are responsible for their own network settings.
    """

    with collection_budget(seconds=config.collection_max_duration_seconds):
        return _collect_source_within_budget(
            source_url, config, discover, fetch_html, validate, classifier, browser
        )


def _collect_source_within_budget(
    source_url, config, discover, fetch_html, validate, classifier, browser,
):
    if discover is None:
        discover = partial(discover_source, config=config)
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
            user_agent=config.user_agent,
        )

    collected_datasets: list[CollectedDataset] = []
    validation_failures: list[ValidationResult] = []
    errors: list[Diagnostic] = []

    rejected_count = 0
    analyzed_count = 0
    discovered_pages: list[DiscoveredPage] = []
    try:
        check_collection_budget()
        discovered_pages = discover(source_url)
        check_collection_budget()
        # Keep the full discovery count for reporting while bounding costly page
        # fetches and LLM calls to the configured analysis limit.
        selected_pages = discovered_pages[: config.max_pages_per_source]
        page_classifier = _classifier_or_default(classifier)

        for discovered_page in selected_pages:
            check_collection_budget()
            analyzed_count += 1
            failure_start = len(validation_failures)
            error_start = len(errors)
            try:
                dataset, _ = _collect_discovered_page_with_report(
                    discovered_page, config, fetch_html, validate, page_classifier,
                    validation_failures=validation_failures, browser=browser,
                    diagnostics=errors,
                )
            except ExtractionError as exception:
                errors.append(Diagnostic(exception.code, "collection"))
                continue
            except PageFetchError as exception:
                if not exception.diagnostics[0].code.startswith("extraction_"):
                    raise
                errors.extend(exception.diagnostics)
                continue
            if dataset is not None:
                collected_datasets.append(dataset)
            else:
                if len(errors) > error_start:
                    continue
                # An alternative failed link does not invalidate a retained dataset.
                inconclusive = [
                    failure
                    for failure in validation_failures[failure_start:]
                    if failure.status in {"unconfirmed", "restricted"}
                ]
                if inconclusive:
                    errors.extend(
                        Diagnostic(
                            "access_restricted"
                            if failure.status == "restricted"
                            else "verification_unconfirmed",
                            "validation",
                            recovery="none" if failure.status == "restricted" else "manual",
                        )
                        for failure in inconclusive
                    )
                else:
                    rejected_count += 1

            check_collection_budget()
    except CollectionBudgetExceeded as exception:
        errors.extend(exception.diagnostics)

    return CollectionResult(
        datasets=collected_datasets,
        report=CollectionReport(
            discovered_count=len(discovered_pages),
            analyzed_count=analyzed_count,
            accepted_count=len(collected_datasets),
            rejected_count=rejected_count,
            invalid_distribution_count=len(validation_failures),
            validation_failures=validation_failures,
            errors=list({(item.code, item.stage, item.recovery): item for item in errors}.values()),
            verification_complete=not errors,
            discovery_methods=tuple(
                sorted(
                    {page.discovery_method for page in discovered_pages if page.discovery_method}
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
    *,
    fetch_json=None,
    browser=None,
    observe=None,
    registry=None,
) -> CollectionResult:
    """Resolve one accepted record with shared validation, never a whole-site crawl."""
    from collector.collection.orchestrator import collect_record

    normalized_url = normalize_http_url(candidate_url)
    if normalized_url is None:
        raise ValueError("Repository candidate URL must be a valid HTTP(S) URL.")
    return collect_record(
        normalized_url,
        config,
        fetch_html=fetch_html,
        fetch_json=fetch_json,
        validate=validate,
        classifier=classifier,
        browser=browser,
        observe=observe,
        registry=registry,
    )


def _collect_discovered_page_with_report(
    discovered_page: DiscoveredPage,
    config: CollectorConfig,
    fetch_html: FetchHTMLFunction,
    validate: ValidateDistributionFunction,
    classifier: PageClassifier | None = None,
    *,
    validation_failures: list[ValidationResult] | None = None,
    browser=None,
    diagnostics: list[Diagnostic] | None = None,
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
        check_collection_budget()
        try:
            fetched_page = fetch_html(discovered_page.url)
            mime_type = fetched_page.content_type.split(";", 1)[0].strip().lower()
            if mime_type and mime_type not in {"text/html", "application/xhtml+xml"}:
                raise PageFetchError(
                    "Landing page did not return HTML.", code="verification_unconfirmed"
                )
            dataset = analyze_html_page(
                fetched_page.final_url, fetched_page.html, config, page_classifier,
                discovered_page=discovered_page,
            )
        except (ExtractionError, PageFetchError) as exception:
            if (isinstance(exception, PageFetchError)
                    and not exception.diagnostics[0].code.startswith("extraction_")):
                raise
            if browser is None:
                raise

            def failed_html(_, *, error=exception):
                raise error

            # The shared record path runs the configured browser fallback and its probes.
            result = collect_repository_candidate_with_report(
                discovered_page.url, config, fetch_html=failed_html,
                validate=validate, classifier=page_classifier, browser=browser,
            )
            if validation_failures is not None:
                validation_failures.extend(result.report.validation_failures)
            if result.report.errors:
                if diagnostics is None:
                    raise PageFetchError(
                        "Source fallback was incomplete.", code=result.report.errors[0].code,
                    ) from exception
                diagnostics.extend(result.report.errors)
            return (
                result.datasets[0] if result.datasets else None,
                result.report.invalid_distribution_count,
            )
        if dataset is not None:
            dataset = replace(
                dataset,
                discovery_method=discovered_page.discovery_method,
            )

    if dataset is None:
        return None, 0

    return _with_valid_distributions_and_report(
        dataset, config, validate, failures=validation_failures,
    )


def _with_valid_distributions_and_report(
    dataset: CollectedDataset,
    config: CollectorConfig,
    validate: ValidateDistributionFunction,
    *,
    failures: list[ValidationResult] | None = None,
) -> tuple[CollectedDataset | None, int]:
    """Keep bounded, successfully probed distributions or reject the dataset."""

    state = ResourceCheckState(failures=failures if failures is not None else [])
    previous_failures = len(state.failures)
    selection = retain_validated_resources(dataset.distributions, config, validate, state=state)
    if not selection.resources:
        return None, len(state.failures) - previous_failures
    return (
        replace(
            dataset, distributions=selection.resources, validation_results=selection.validations,
        ),
        len(state.failures) - previous_failures,
    )
