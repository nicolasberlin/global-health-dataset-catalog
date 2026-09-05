"""Immutable data contracts shared across the collection pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from collector.extraction.dataset_metadata import (
    build_dataset_metadata,
)
from collector.url_utils import require_http_url


@dataclass(frozen=True)
class LinkCandidate:
    """Page link and surrounding evidence considered during extraction."""

    url: str
    anchor: str = ""
    nearby_text: str = ""
    extension: str = ""
    same_domain: bool = False
    dom_path: str = ""


@dataclass(frozen=True)
class PageSnapshot:
    """Classifier evidence assembled from HTML or repository metadata.

    ``search_query`` is populated for repository relevance checks, while
    ``dataset_url`` is the preferred dataset identity. ``links`` and
    ``json_ld`` retain extraction evidence that has not been flattened into
    the normalized metadata fields.
    """

    url: str
    canonical_url: str
    search_query: str = ""
    title: str = ""
    geography: tuple[str, ...] = ()
    date_of_publication: str = ""
    dataset_url: str = ""
    diseases: tuple[str, ...] = ()
    size_of_dataset: str = ""
    demographic_information: tuple[str, ...] = ()
    sharing_license: str = ""
    modality_of_data: tuple[str, ...] = ()
    description_of_dataset: str = ""
    h1: str = ""
    meta_description: str = ""
    og_title: str = ""
    og_description: str = ""
    headings: tuple[str, ...] = ()
    text: str = ""
    publisher: str = ""
    hosting_platform: str = ""
    uploader: str = ""
    links: tuple[LinkCandidate, ...] = ()
    json_ld: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "search_query", self.search_query.strip())
        object.__setattr__(self, "title", _first_text(self.title, self.h1, self.og_title))
        object.__setattr__(self, "geography", _normalized_values(self.geography))
        object.__setattr__(self, "date_of_publication", self.date_of_publication.strip())
        object.__setattr__(
            self,
            "dataset_url",
            _first_text(self.dataset_url, self.canonical_url, self.url),
        )
        object.__setattr__(self, "diseases", _normalized_values(self.diseases))
        object.__setattr__(self, "size_of_dataset", self.size_of_dataset.strip())
        object.__setattr__(
            self,
            "demographic_information",
            _normalized_values(self.demographic_information),
        )
        object.__setattr__(self, "sharing_license", self.sharing_license.strip())
        object.__setattr__(
            self,
            "modality_of_data",
            _normalized_values(self.modality_of_data),
        )
        object.__setattr__(
            self,
            "description_of_dataset",
            _first_text(
                self.description_of_dataset,
                self.meta_description,
                self.og_description,
            ),
        )

    def dataset_metadata(self) -> dict[str, str]:
        """Return the fixed metadata contract supplied to classification."""

        return build_dataset_metadata(
            title=self.title,
            geography=self.geography,
            date_of_publication=self.date_of_publication,
            dataset_url=self.dataset_url,
            diseases=self.diseases,
            size_of_dataset=self.size_of_dataset,
            demographic_information=self.demographic_information,
            sharing_license=self.sharing_license,
            modality_of_data=self.modality_of_data,
            description_of_dataset=self.description_of_dataset,
        )


def _first_text(*values: str) -> str:
    return next((value.strip() for value in values if value.strip()), "")


def _normalized_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


@dataclass(frozen=True)
class DistributionCandidate:
    """Potential data resource emitted before HTTP validation.

    ``probability`` ranks extraction evidence; it does not prove that the
    resource is reachable. ``signals`` preserves the evidence behind that
    ranking, and lifecycle timestamps are populated after persistence.
    """

    url: str
    format: str
    probability: float
    anchor: str = ""
    extension: str = ""
    mime_type: str = ""
    nearby_text: str = ""
    same_domain: bool = False
    dom_path: str = ""
    signals: dict[str, object] = field(default_factory=dict)
    first_seen_at: str = ""
    last_seen_at: str = ""
    last_checked_at: str = ""


@dataclass(frozen=True)
class HTTPProbe:
    """Raw bounded HTTP probe outcome used to validate a distribution."""

    url: str
    final_url: str
    status_code: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body_sample: bytes = b""
    error: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """Bounded HTTP-probe result used to retain or reject a distribution.

    ``final_url`` records the destination after redirects, and ``format`` may
    be refined from response headers or a body sample. ``ok`` confirms the
    resource response, not the dataset's semantic relevance.
    """

    url: str
    final_url: str
    format: str
    ok: bool
    http_status: int | None
    mime_type: str = ""
    size_bytes: int | None = None
    etag: str = ""
    last_modified: str = ""
    content_disposition: str = ""
    error: str = ""


@dataclass(frozen=True)
class CollectedDataset:
    """Dataset assembled after page acceptance and prepared for persistence.

    Before validation, ``distributions`` may still contain candidates; the
    completed collection keeps only validated resources and their
    ``validation_results``. ``dataset_signals`` is the classifier audit trail,
    while database identifiers and lifecycle timestamps are added on storage.
    """

    dataset_url: str
    title: str
    description: str
    publisher: str
    hosting_platform: str
    uploader: str
    dataset_signals: dict[str, object]
    geography: tuple[str, ...] = ()
    distributions: list[DistributionCandidate] = field(default_factory=list)
    discovery_method: str = ""
    validation_results: list[ValidationResult] = field(default_factory=list)
    source_url: str = ""
    database_id: int | None = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_url", require_http_url(self.dataset_url))


@dataclass(frozen=True)
class CollectionReport:
    """Aggregate counters and discovery methods for one collection run.

    ``accepted_count`` counts datasets retained after distribution validation,
    not every positive page-classifier response.
    """

    discovered_count: int = 0
    analyzed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    invalid_distribution_count: int = 0
    discovery_methods: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectionResult:
    """Transient collector output later persisted by the backend completion step."""

    datasets: list[CollectedDataset] = field(default_factory=list)
    report: CollectionReport = field(default_factory=CollectionReport)
