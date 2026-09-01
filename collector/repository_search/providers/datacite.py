from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlencode

from collector.discovery.adapters import fetch_json_url
from collector.extraction.dataset_metadata import build_dataset_metadata
from collector.extraction.extractor import html_to_text
from collector.repository_search.filtering import _http_url, _text
from collector.repository_search.models import (
    MISSING_METADATA_VALUE,
    JsonFetcher,
    RepositorySearchResult,
)

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
        for item in items:
            if not isinstance(item, dict):
                continue

            result = _datacite_result(item)
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


def _datacite_result(item: dict[object, object]) -> RepositorySearchResult | None:
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

    return RepositorySearchResult(
        title=title,
        description=description,
        url=url,
        source="DataCite",
        publisher=_publisher(attributes),
        date=date,
        doi=doi,
        keywords=keywords,
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
