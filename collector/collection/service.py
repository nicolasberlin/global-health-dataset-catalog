"""Public collection entry points delegating to the source and record workflows."""

from __future__ import annotations

from collector.collection.contracts import DiscoverFunction as DiscoverFunction
from collector.collection.contracts import FetchHTMLFunction as FetchHTMLFunction
from collector.collection.contracts import (
    ValidateDistributionFunction as ValidateDistributionFunction,
)
from collector.collection.eligibility.models import PageClassifier
from collector.collection.pipeline import analyze_discovered_page as analyze_discovered_page
from collector.collection.pipeline import analyze_html_page as analyze_html_page
from collector.collection.workflows import record, source
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.storage.models import CollectionResult


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
    """Collect a bounded source through its discovery, analysis and validation workflow."""
    return source.collect_source_with_report(
        source_url, config, discover, fetch_html, validate, classifier, browser=browser,
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
    """Collect one repository record through the API, HTML and browser workflow."""
    return record.collect_repository_candidate_with_report(
        candidate_url, config, fetch_html, validate, classifier,
        fetch_json=fetch_json, browser=browser, observe=observe, registry=registry,
    )
