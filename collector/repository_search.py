from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Optional, Protocol
from urllib.parse import urlencode, urlsplit

from collector.classification.page import PageClassificationError
from collector.classification.repository import (
    RepositoryClassification,
    RepositoryResultClassifier,
)
from collector.discovery.adapters import fetch_json_url
from collector.extraction.dataset_metadata import (
    MISSING_DATASET_METADATA_VALUE,
    build_dataset_metadata,
    normalize_dataset_metadata,
)
from collector.extraction.extractor import html_to_text
from collector.storage.models import PageSnapshot

JsonFetcher = Callable[[str], dict[str, object]]
logger = logging.getLogger(__name__)
PROVIDER_UNAVAILABLE_MESSAGE = "This source could not be searched."
INVALID_METADATA_MESSAGE = "Some results were omitted because their metadata was invalid."
CLASSIFICATION_UNAVAILABLE_MESSAGE = "Some results could not be classified."
MISSING_METADATA_VALUE = MISSING_DATASET_METADATA_VALUE
DISEASE_TERMS = (
    "aids",
    "cancer",
    "cholera",
    "coronavirus",
    "covid",
    "dengue",
    "diabetes",
    "ebola",
    "hepatitis",
    "hiv",
    "influenza",
    "malaria",
    "measles",
    "polio",
    "smallpox",
    "tuberculosis",
    "zika",
)
GENERIC_HEALTH_SUBJECTS = {
    "data",
    "dataset",
    "datasets",
    "disease",
    "diseases",
    "epidemiology",
    "health",
    "medicine",
    "morbidity",
    "mortality",
    "public health",
    "surveillance",
}
DEMOGRAPHIC_TERMS = (
    "age",
    "sex",
    "gender",
    "height",
    "weight",
    "race",
    "ethnicity",
    "pregnancy",
    "maternal",
    "income",
    "education",
    "occupation",
    "children",
    "adolescent",
    "adult",
    "elderly",
)
FORMAT_MODALITY_MAP = {
    "CSV": "tabular",
    "TSV": "tabular",
    "XLS": "tabular",
    "XLSX": "tabular",
    "PARQUET": "tabular",
    "JSON": "structured data",
    "JSONL": "structured data",
    "XML": "structured data",
    "TXT": "text",
    "TEXT": "text",
    "PDF": "text",
    "DICOM": "images",
    "JPEG": "images",
    "JPG": "images",
    "PNG": "images",
    "TIFF": "images",
    "MP3": "speech/audio",
    "WAV": "speech/audio",
    "MP4": "video",
    "FASTA": "genomic sequence",
    "FASTQ": "genomic sequence",
}
TEXT_MODALITY_TERMS = {
    "speech": "speech",
    "voice": "speech",
    "audio": "speech/audio",
    "text": "text",
    "transcript": "text",
    "image": "images",
    "images": "images",
    "imaging": "images",
    "x-ray": "images",
    "xray": "images",
    "video": "video",
    "genomic": "genomic sequence",
    "genome": "genomic sequence",
}


@dataclass(frozen=True)
class RepositorySearchResult:
    title: str
    url: str
    source: str
    search_query: str = ""
    description: str = ""
    publisher: str = ""
    date: str = ""
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)
    classification: RepositoryClassification | None = None


@dataclass(frozen=True)
class RepositorySearchWarning:
    message: str = PROVIDER_UNAVAILABLE_MESSAGE
    provider: Optional[str] = None  # noqa: UP045 - Keep Python 3.9-compatible typing.


@dataclass(frozen=True)
class RepositorySearchResponse:
    results: list[RepositorySearchResult] = field(default_factory=list)
    warnings: list[RepositorySearchWarning] = field(default_factory=list)


class RepositorySearchProvider(Protocol):
    name: str

    def search(self, query: str) -> list[RepositorySearchResult]:
        ...


class DataCiteRepositorySearchProvider:
    name = "DataCite"
    _base_url = "https://api.datacite.org/dois"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        page_size: int = 10,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._page_size = page_size

    def search(self, query: str) -> list[RepositorySearchResult]:
        data = self._fetch_json(self._search_url(query))
        items = data.get("data")
        if not isinstance(items, list):
            raise ValueError("Invalid DataCite response shape: expected data list.")

        results: list[RepositorySearchResult] = []
        for rank, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            result = _datacite_result(item, rank)
            if result is not None:
                results.append(result)

        return results

    def _search_url(self, query: str) -> str:
        params = {
            "query": query,
            "resource-type-id": "dataset",
            "page[size]": str(self._page_size),
            "sort": "relevance",
        }
        return f"{self._base_url}?{urlencode(params)}"


def search_repository_metadata(
    query: str,
    providers: Iterable[RepositorySearchProvider] | None = None,
) -> RepositorySearchResponse:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Search query is required")

    active_providers = (
        list(providers) if providers is not None else [DataCiteRepositorySearchProvider()]
    )
    results: list[RepositorySearchResult] = []
    errors: list[str] = []
    warnings: list[RepositorySearchWarning] = []
    successful_provider_count = 0

    for provider in active_providers:
        try:
            provider_results = provider.search(normalized_query)
        except ValueError as exception:
            error = f"{provider.name}: {exception}"
            errors.append(error)
            logger.warning("Repository search provider failed: %s", error)
            warnings.append(RepositorySearchWarning(provider=provider.name))
            continue

        successful_provider_count += 1
        results.extend(
            replace(result, search_query=normalized_query)
            for result in provider_results
        )

    if successful_provider_count == 0 and errors:
        raise ValueError("All repository providers failed.")

    filtered_results, rejected_result_count = filter_repository_results(results)
    if rejected_result_count:
        warnings.append(RepositorySearchWarning(message=INVALID_METADATA_MESSAGE))

    return RepositorySearchResponse(
        results=sorted(
            filtered_results,
            key=lambda result: result.relevance_score,
            reverse=True,
        ),
        warnings=warnings,
    )


def filter_repository_results(
    results: Iterable[RepositorySearchResult],
) -> tuple[list[RepositorySearchResult], int]:
    filtered_results: list[RepositorySearchResult] = []
    rejected_result_count = 0
    for result in results:
        title = _text(result.title)
        url = _http_url(_text(result.url))
        relevance_score = _number(result.relevance_score)
        if (
            not title
            or not url
            or relevance_score is None
            or relevance_score < 0
            or relevance_score > 1
        ):
            rejected_result_count += 1
            continue

        filtered_results.append(
            replace(
                result,
                title=title,
                url=url,
                relevance_score=round(relevance_score, 4),
            )
        )

    return filtered_results, rejected_result_count


def classify_repository_results(
    results: Iterable[RepositorySearchResult],
    classifier: RepositoryResultClassifier,
) -> tuple[list[RepositorySearchResult], list[RepositorySearchWarning]]:
    """Classify repository results from their normalized metadata contract."""
    classified_results: list[RepositorySearchResult] = []
    failed_count = 0

    for result in results:
        try:
            classified_result = classify_repository_result(result, classifier)
        except PageClassificationError as exception:
            failed_count += 1
            logger.warning(
                "Repository result classification failed for %s: %s",
                result.url,
                exception,
            )
            classified_results.append(result)
            continue

        classified_results.append(classified_result)

    warnings = (
        [RepositorySearchWarning(message=CLASSIFICATION_UNAVAILABLE_MESSAGE)]
        if failed_count
        else []
    )
    return classified_results, warnings


def classify_repository_result(
    result: RepositorySearchResult,
    classifier: RepositoryResultClassifier,
) -> RepositorySearchResult:
    """Classify one repository result from its normalized metadata contract."""
    classification = classifier.classify(_repository_result_page(result))
    return replace(result, classification=classification)


def _repository_result_page(result: RepositorySearchResult) -> PageSnapshot:
    metadata = normalize_dataset_metadata(result.metadata)
    title = _metadata_text(metadata["Title"], fallback=result.title)
    description = _metadata_text(
        metadata["Description of dataset"],
        fallback=result.description,
    )
    return PageSnapshot(
        url=result.url,
        canonical_url=result.url,
        search_query=result.search_query,
        title=title,
        meta_description=description,
        publisher=result.publisher,
        geography=_metadata_items(metadata["Geography"]),
        date_of_publication=_metadata_text(
            metadata["Date of publication"],
            fallback=result.date,
        ),
        dataset_url=_metadata_text(metadata["Dataset URL"], fallback=result.url),
        diseases=_metadata_items(metadata["Disease(s)"]),
        size_of_dataset=_metadata_text(metadata["Size of dataset"]),
        demographic_information=_metadata_items(
            metadata["Demographic information"]
        ),
        sharing_license=_metadata_text(metadata["Sharing license"]),
        modality_of_data=_metadata_items(metadata["Modality of data"]),
        description_of_dataset=description,
        text=" ".join(
            value
            for value in (result.title, result.description, " ".join(result.keywords))
            if value
        ),
    )


def _metadata_text(value: str, *, fallback: str = "") -> str:
    return fallback if value == MISSING_METADATA_VALUE else value


def _metadata_items(value: str) -> tuple[str, ...]:
    if value == MISSING_METADATA_VALUE:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _datacite_result(
    item: dict[object, object],
    rank: int,
) -> RepositorySearchResult | None:
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return None

    doi = _doi(item, attributes)
    url = _http_url(_text(attributes.get("url"))) or _doi_url(doi)
    extracted_title = _title(attributes)
    title = extracted_title or url
    if not title or not url:
        return None

    description = _description(attributes)
    date = _date(attributes)
    keywords = _subjects(attributes)
    native_score = _number(attributes.get("score"))
    if native_score is None:
        native_score = _number(item.get("score"))

    return RepositorySearchResult(
        title=title,
        description=description,
        url=url,
        source="DataCite",
        publisher=_publisher(attributes),
        date=date,
        doi=doi,
        keywords=keywords,
        relevance_score=_relevance_score(native_score, rank),
        metadata=_search_result_metadata(
            attributes,
            title=extracted_title,
            url=url,
            date=date,
            description=description,
            subjects=keywords,
        ),
    )


def _search_result_metadata(
    attributes: dict[object, object],
    *,
    title: str,
    url: str,
    date: str,
    description: str,
    subjects: list[str],
) -> dict[str, str]:
    searchable_text = " ".join([title, description, " ".join(subjects)])
    return build_dataset_metadata(
        title=title,
        geography=_geography(attributes),
        date_of_publication=date,
        dataset_url=url,
        diseases=_diseases(subjects, searchable_text),
        size_of_dataset=_metadata_values(_dataset_sizes(attributes, description)),
        demographic_information=_demographic_information(searchable_text),
        sharing_license=_metadata_values(_sharing_license(attributes)),
        modality_of_data=_data_modalities(attributes, searchable_text),
        description_of_dataset=description,
    )


def _metadata_value(value: str) -> str:
    return _metadata_values([value])


def _metadata_values(values: Iterable[str]) -> str:
    normalized_values: list[str] = []
    for value in values:
        normalized_value = html_to_text(value)
        if normalized_value and normalized_value not in normalized_values:
            normalized_values.append(normalized_value)

    return ", ".join(normalized_values) if normalized_values else MISSING_METADATA_VALUE


def _geography(attributes: dict[object, object]) -> list[str]:
    values: list[str] = []
    for location in _metadata_dict_items(attributes.get("geoLocations")):
        values.extend(
            _metadata_text_values(
                location.get("geoLocationPlace"),
                keys=("name", "@value", "value"),
            )
        )
        values.extend(
            _metadata_text_values(
                location.get("geoLocationCountry"),
                keys=("name", "@value", "value"),
            )
        )

        point = _geo_point(location.get("geoLocationPoint"))
        if point:
            values.append(point)

        box = _geo_box(location.get("geoLocationBox"))
        if box:
            values.append(box)

    for key in ("country", "countries", "coverage", "spatialCoverage"):
        values.extend(
            _metadata_text_values(
                attributes.get(key),
                keys=("name", "country", "@value", "value"),
            )
        )

    return values


def _diseases(subjects: list[str], searchable_text: str) -> list[str]:
    values: list[str] = []
    for subject in subjects:
        normalized_subject = _normalize_for_matching(subject)
        if not normalized_subject or normalized_subject in GENERIC_HEALTH_SUBJECTS:
            continue
        if any(_contains_term(normalized_subject, term) for term in DISEASE_TERMS):
            values.append(subject)
        elif "disease" in normalized_subject and normalized_subject not in {"disease", "diseases"}:
            values.append(subject)

    if values:
        return values

    normalized_text = _normalize_for_matching(searchable_text)
    return [term for term in DISEASE_TERMS if _contains_term(normalized_text, term)]


def _dataset_sizes(attributes: dict[object, object], description: str) -> list[str]:
    values = _metadata_text_values(attributes.get("sizes"))
    values.extend(_metadata_text_values(attributes.get("size")))
    if values:
        return values

    size_patterns = (
        r"\b(?:sample size|population sample|n)\s*[:=]\s*"
        r"[0-9][0-9,.\s]*(?:participants|patients|records|samples|observations|people|individuals)?",
        r"\b[0-9][0-9,.\s]*\s+"
        r"(?:participants|patients|records|samples|observations|people|individuals)\b",
    )
    matches: list[str] = []
    for pattern in size_patterns:
        for match in re.finditer(pattern, description, flags=re.IGNORECASE):
            matches.append(match.group(0))

    return matches


def _demographic_information(searchable_text: str) -> list[str]:
    normalized_text = _normalize_for_matching(searchable_text)
    return [term for term in DEMOGRAPHIC_TERMS if _contains_term(normalized_text, term)]


def _sharing_license(attributes: dict[object, object]) -> list[str]:
    values: list[str] = []
    for rights_item in _metadata_dict_items(attributes.get("rightsList")):
        rights = _metadata_text_values(rights_item.get("rights"))
        rights_identifier = _metadata_text_values(rights_item.get("rightsIdentifier"))
        rights_uri = _metadata_text_values(rights_item.get("rightsUri"))
        values.extend([*rights, *rights_identifier, *rights_uri])

    for key in ("rights", "license", "licenses"):
        values.extend(
            _metadata_text_values(
                attributes.get(key),
                keys=("rights", "name", "title", "url", "uri", "@value", "value"),
            )
        )

    return values


def _data_modalities(attributes: dict[object, object], searchable_text: str) -> list[str]:
    values: list[str] = []
    for data_format in _metadata_text_values(attributes.get("formats")):
        values.extend(_modalities_from_format(data_format))

    normalized_text = _normalize_for_matching(searchable_text)
    for term, modality in TEXT_MODALITY_TERMS.items():
        if _contains_term(normalized_text, term):
            values.append(modality)

    return values


def _modalities_from_format(data_format: str) -> list[str]:
    normalized_format = re.sub(r"[^A-Z0-9]+", " ", data_format.upper())
    tokens = normalized_format.split()
    values = [
        modality
        for token in tokens
        if (modality := FORMAT_MODALITY_MAP.get(token)) is not None
    ]

    if "IMAGE" in tokens:
        values.append("images")
    if "AUDIO" in tokens:
        values.append("speech/audio")
    if "VIDEO" in tokens:
        values.append("video")

    return values


def _metadata_text_values(
    value: object,
    *,
    keys: tuple[str, ...] = (),
) -> list[str]:
    if isinstance(value, str):
        text = html_to_text(value)
        return [text] if text else []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [
            text
            for item in value
            for text in _metadata_text_values(item, keys=keys)
        ]
    if isinstance(value, dict):
        if not keys:
            return []

        return [
            text
            for key in keys
            for text in _metadata_text_values(value.get(key))
        ]

    return []


def _metadata_dict_items(value: object) -> list[dict[object, object]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _geo_point(value: object) -> str:
    if not isinstance(value, dict):
        return ""

    latitude = _text(value.get("pointLatitude")) or _text(value.get("latitude"))
    longitude = _text(value.get("pointLongitude")) or _text(value.get("longitude"))
    if latitude and longitude:
        return f"{latitude}, {longitude}"

    return ""


def _geo_box(value: object) -> str:
    if not isinstance(value, dict):
        return ""

    west = _text(value.get("westBoundLongitude"))
    east = _text(value.get("eastBoundLongitude"))
    south = _text(value.get("southBoundLatitude"))
    north = _text(value.get("northBoundLatitude"))
    if west and east and south and north:
        return f"{south}, {west} to {north}, {east}"

    return ""


def _normalize_for_matching(value: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(value).casefold()).strip()


def _contains_term(normalized_text: str, normalized_term: str) -> bool:
    return re.search(rf"\b{re.escape(normalized_term)}\b", normalized_text) is not None


def _title(attributes: dict[object, object]) -> str:
    titles = attributes.get("titles")
    if not isinstance(titles, list):
        return ""

    for title in titles:
        if isinstance(title, dict):
            text = html_to_text(_text(title.get("title")))
            if text:
                return text

    return ""


def _description(attributes: dict[object, object]) -> str:
    descriptions = attributes.get("descriptions")
    if not isinstance(descriptions, list):
        return ""

    fallback = ""
    for description in descriptions:
        if not isinstance(description, dict):
            continue

        text = html_to_text(_text(description.get("description")))
        if not text:
            continue

        if _text(description.get("descriptionType")).lower() == "abstract":
            return text
        if not fallback:
            fallback = text

    return fallback


def _publisher(attributes: dict[object, object]) -> str:
    publisher = attributes.get("publisher")
    if isinstance(publisher, dict):
        return _text(publisher.get("name"))

    return _text(publisher)


def _date(attributes: dict[object, object]) -> str:
    publication_year = attributes.get("publicationYear")
    if isinstance(publication_year, (int, str)):
        return str(publication_year).strip()

    dates = attributes.get("dates")
    if isinstance(dates, list):
        preferred_types = {"issued", "publicationdate", "created", "available"}
        fallback = ""
        for date_item in dates:
            if not isinstance(date_item, dict):
                continue

            date_value = _text(date_item.get("date"))
            if not date_value:
                continue

            date_type = _text(date_item.get("dateType")).replace(" ", "").lower()
            if date_type in preferred_types:
                return date_value
            if not fallback:
                fallback = date_value

        if fallback:
            return fallback

    for key in ("published", "created", "updated"):
        value = _text(attributes.get(key))
        if value:
            return value

    return ""


def _doi(
    item: dict[object, object],
    attributes: dict[object, object],
) -> str:
    doi = _text(attributes.get("doi")) or _text(item.get("id"))
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""


def _http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.hostname:
        return value
    return ""


def _subjects(attributes: dict[object, object]) -> list[str]:
    subjects = attributes.get("subjects")
    if not isinstance(subjects, list):
        return []

    values: list[str] = []
    for subject in subjects:
        if not isinstance(subject, dict):
            continue

        text = html_to_text(_text(subject.get("subject")))
        if text and text not in values:
            values.append(text)

    return values


def _relevance_score(native_score: float | None, rank: int) -> float:
    if native_score is not None and 0 <= native_score <= 1:
        return round(native_score, 4)

    return max(0.0, round(1.0 - (rank * 0.05), 4))


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
