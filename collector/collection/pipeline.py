"""Shared page preparation and classification, independent of entry points."""

from __future__ import annotations

from dataclasses import replace

from collector.budget import check_collection_budget
from collector.classification.factory import build_default_page_classifier
from collector.classification.page import PageClassifier
from collector.collection.contracts import StrategyResult
from collector.collection.records import NormalizedRecord
from collector.config import DEFAULT_CONFIG, CollectorConfig
from collector.discovery.adapters.shared import EXCLUDED_RESOURCE_FORMATS, DiscoveredPage
from collector.extraction.distributions import EXCLUDED_EXTENSIONS, extract_distributions
from collector.extraction.errors import ExtractionError
from collector.extraction.extractor import extract_page
from collector.network.fetch import PageFetchError
from collector.storage.metadata import metadata_evidence, normalize_doi
from collector.storage.models import CollectedDataset, DistributionCandidate, PageSnapshot
from collector.url_utils import normalize_http_url
from collector.validation.distributions import page_access_diagnostic


def analyze_html_page(
    url: str,
    html: str,
    config: CollectorConfig = DEFAULT_CONFIG,
    classifier: PageClassifier | None = None,
    *,
    discovered_page: DiscoveredPage | None = None,
    distribution_candidates: list[DistributionCandidate] | None = None,
    record_url: str | None = None,
    record_identity: dict[str, str] | None = None,
    page_snapshot: PageSnapshot | None = None,
) -> CollectedDataset | None:
    """Extract and classify one HTML page before distribution validation.

    A valid rejection returns ``None``. Classifier failures, including an
    unavailable default EPFL RCP voter, propagate as errors rather than being
    counted as rejected pages. This function performs no persistence.
    """

    page = (page_snapshot if page_snapshot is not None else extract_page(
        url, html, expected_identity=(
            record_identity or (discovered_page.record_identity if discovered_page else None)
        ),
    ))
    if record_url is not None:
        page = replace(page, dataset_url=record_url, canonical_url=record_url)
    if (record_identity and record_identity.get("kind") == "file"
            and not page.dataset_metadata_ambiguous):
        # File pages can expose the parent's citation DOI in their HTML metadata.
        page = replace(page, doi=normalize_doi(record_identity.get("persistent_id")))
    evidence = metadata_evidence(page, kind="page", source_url=page.url)
    if discovered_page is not None and not page.dataset_metadata_ambiguous:
        page = _merge_discovery_metadata(page, discovered_page)
        for field in ("date_of_publication", "sharing_license", "doi"):
            value = getattr(discovered_page, field)
            if value:
                evidence.setdefault(field, []).append(
                    {
                        "value": value,
                        "kind": "adapter",
                        "source_url": discovered_page.metadata_source_url or discovered_page.url,
                    }
                )
    candidates = (extract_distributions(page) if distribution_candidates is None
                  else distribution_candidates)
    distributions = [item for item in candidates if _usable_distribution(item)]
    if not distributions:
        if page.dataset_metadata_ambiguous:
            raise ExtractionError(
                "Dataset identity remains ambiguous.", code="dataset_identity_ambiguous",
            )
        barrier = page_access_diagnostic(html)
        if barrier is not None:
            raise PageFetchError(barrier.message, code=barrier.code)
        return None
    page_classifier = _classifier_or_default(classifier)
    check_collection_budget()
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
        record_identity=(record_identity if record_identity is not None
                         else discovered_page.record_identity if discovered_page else {}),
        dataset_signals=classification.dataset_signals,
        distributions=distributions,
    )

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
        doi=discovered_page.doi,
        hosting_platform=discovered_page.hosting_platform,
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
    check_collection_budget()
    classification = page_classifier.classify(page, distributions)

    if not classification.accepted:
        return None

    return CollectedDataset(
        dataset_url=page.dataset_url,
        title=page.title or page.canonical_url,
        description=page.meta_description,
        publisher=page.publisher,
        hosting_platform=page.hosting_platform,
        uploader="",
        geography=page.geography,
        date_of_publication=page.date_of_publication,
        sharing_license=page.sharing_license,
        doi=page.doi,
        metadata_provenance=metadata_evidence(
            page,
            kind="adapter",
            source_url=discovered_page.metadata_source_url or page.url,
        ),
        dataset_signals=classification.dataset_signals,
        record_identity=discovered_page.record_identity,
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
        and distribution.extension.lower() not in EXCLUDED_EXTENSIONS
        and distribution.mime_type.lower().split(";", 1)[0].strip() != "application/pdf"
        and "html" not in distribution.mime_type.lower()
    )

def _merge_discovery_metadata(page: PageSnapshot, discovered: DiscoveredPage) -> PageSnapshot:
    """Fill missing page fields before classification, retaining the extracted links."""
    fields = (
        "title",
        "doi",
        "hosting_platform",
        "publisher",
        "geography",
        "date_of_publication",
        "diseases",
        "size_of_dataset",
        "demographic_information",
        "sharing_license",
        "modality_of_data",
    )
    return replace(
        page,
        **{field: getattr(page, field) or getattr(discovered, field) for field in fields},
        meta_description=page.meta_description or page.og_description or discovered.description,
        description_of_dataset=page.description_of_dataset or discovered.description,
        text=" ".join((page.text, discovered.title, discovered.description, discovered.publisher)),
    )


def eligible_resources(
    resolved: StrategyResult, *, expected_identity: dict[str, str] | None = None,
) -> list[DistributionCandidate]:
    resources = list(resolved.page.distributions)
    if resolved.html:
        if resolved.snapshot is None:
            resolved.snapshot = extract_page(
                resolved.page.url, resolved.html, expected_identity=expected_identity,
            )
        resources = extract_distributions(resolved.snapshot)
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
    if resolved.html:
        from collector.collection.compatibility import to_strategy_result

        return analyze_html_page(
            resolved.page.url, resolved.html, config, classifier,
            distribution_candidates=resources, record_url=record_url,
            record_identity=record_identity, page_snapshot=resolved.snapshot,
            discovered_page=to_strategy_result(known_record, resolved.page.discovery_method).page
            if known_record else None,
        )
    return analyze_discovered_page(
        replace(resolved.page, distributions=tuple(resources)), config, classifier,
    )
