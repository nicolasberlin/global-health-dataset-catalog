"""Shared discovery contracts, metadata helpers, and bounded JSON fetching."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request

from collector.config import DEFAULT_CONFIG
from collector.fetch import open_public_http_url
from collector.storage.models import DistributionCandidate

JsonFetcher = Callable[[str], dict[str, object]]

EXCLUDED_RESOURCE_FORMATS = {"HTML", "HTM", "PDF", "PNG", "JPG", "JPEG", "GIF", "SVG"}

# These vocabularies enrich metadata only; they do not accept or reject a page.
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
DEMOGRAPHIC_TERMS = (
    "age",
    "sex",
    "gender",
    "race",
    "ethnicity",
    "pregnancy",
    "maternal",
    "children",
    "adolescent",
    "adult",
    "elderly",
)
FORMAT_MODALITIES = {
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


@dataclass(frozen=True)
class DiscoveredPage:
    """Normalized page candidate and metadata emitted by a discovery adapter."""

    url: str
    discovery_method: str
    priority: float = 0.0
    title: str = ""
    description: str = ""
    publisher: str = ""
    geography: tuple[str, ...] = ()
    date_of_publication: str = ""
    diseases: tuple[str, ...] = ()
    size_of_dataset: str = ""
    demographic_information: tuple[str, ...] = ()
    sharing_license: str = ""
    modality_of_data: tuple[str, ...] = ()
    distributions: tuple[DistributionCandidate, ...] = ()
    discovery_metadata: dict[str, object] = field(default_factory=dict)


class DiscoveryAdapter(Protocol):
    """Interface for source-specific discovery strategies."""

    name: str

    def detect(self, source_url: str) -> bool:
        ...

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        ...


def fetch_json_url(
    url: str,
    timeout: float = DEFAULT_CONFIG.request_timeout_seconds,
    max_bytes: int = 5_000_000,
) -> dict[str, object]:
    """Fetch a bounded public URL and require a JSON object response."""

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": DEFAULT_CONFIG.user_agent,
        },
        method="GET",
    )

    try:
        with open_public_http_url(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
    except HTTPError as exception:
        raise ValueError(f"JSON URL returned HTTP {exception.code}.") from exception
    except (TimeoutError, URLError, OSError) as exception:
        raise ValueError(f"Could not fetch JSON URL: {exception}") from exception

    if len(body) > max_bytes:
        raise ValueError("JSON response is too large for discovery.")

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exception:
        raise ValueError("JSON URL did not return valid JSON.") from exception

    if not isinstance(data, dict):
        raise ValueError("JSON URL did not return an object.")

    return data


def _geography_from_mapping(mapping: dict[object, object]) -> list[str]:
    geography: list[str] = []
    for key in (
        "country",
        "countries",
        "coverage",
        "dct:coverage",
        "spatial",
        "dct:spatial",
        "spatialCoverage",
        "spatial_coverage",
        "geographic_coverage",
        "geographical_coverage",
    ):
        geography.extend(_country_values(mapping.get(key)))

    extras = mapping.get("extras")
    if isinstance(extras, list):
        for extra in extras:
            if not isinstance(extra, dict):
                continue

            extra_key = _text(extra.get("key") or extra.get("name")).lower()
            if extra_key in {
                "country",
                "countries",
                "coverage",
                "spatial",
                "geographic_coverage",
                "geographical_coverage",
            }:
                geography.extend(_country_values(extra.get("value")))

    return _dedupe(geography)


def _publication_date_from_mapping(mapping: dict[object, object]) -> str:
    return _first_mapping_value(
        mapping,
        "date_published",
        "datePublished",
        "publication_date",
        "publicationDate",
        "issued",
        "dct:issued",
        "release_date",
        "releaseDate",
        "createdAt",
        "created_at",
    )


def _diseases_from_mapping(*mappings: dict[object, object]) -> tuple[str, ...]:
    values: list[str] = []
    for mapping in mappings:
        values.extend(
            _mapping_values(
                mapping,
                "disease",
                "diseases",
                "condition",
                "conditions",
                "keyword",
                "keywords",
                "tags",
                "theme",
                "category",
                "categories",
            )
        )
        values.extend(
            [
                _first_text(mapping, "title", "name", "dct:title"),
                _first_text(mapping, "description", "notes", "dct:description"),
            ]
        )

    searchable_text = " ".join(values).casefold()
    return tuple(
        term
        for term in DISEASE_TERMS
        if re.search(rf"\b{re.escape(term)}\b", searchable_text)
    )


def _demographics_from_mapping(*mappings: dict[object, object]) -> tuple[str, ...]:
    values: list[str] = []
    for mapping in mappings:
        values.extend(
            _mapping_values(
                mapping,
                "demographic_information",
                "demographics",
                "population",
                "population_coverage",
                "keyword",
                "keywords",
                "tags",
            )
        )
        values.extend(
            [
                _first_text(mapping, "title", "name", "dct:title"),
                _first_text(mapping, "description", "notes", "dct:description"),
            ]
        )

    searchable_text = " ".join(values).casefold()
    return tuple(
        term
        for term in DEMOGRAPHIC_TERMS
        if re.search(rf"\b{re.escape(term)}\b", searchable_text)
    )


def _modalities_from_distributions(
    distributions: tuple[DistributionCandidate, ...],
) -> tuple[str, ...]:
    values = [
        modality
        for distribution in distributions
        if (modality := FORMAT_MODALITIES.get(distribution.format.upper()))
    ]
    return tuple(_dedupe(values))


def _modalities_from_format(value: str) -> list[str]:
    tokens = re.sub(r"[^A-Z0-9]+", " ", value.upper()).split()
    tabular_tokens = {"CSV", "TSV", "XLS", "XLSX", "PARQUET"}
    values = [
        FORMAT_MODALITIES[token]
        for token in tokens
        if token in FORMAT_MODALITIES
        and not (token == "TEXT" and any(item in tabular_tokens for item in tokens))
    ]
    if "IMAGE" in tokens:
        values.append("images")
    if "AUDIO" in tokens:
        values.append("speech/audio")
    if "VIDEO" in tokens:
        values.append("video")
    return values


def _first_mapping_value(mapping: dict[object, object], *keys: str) -> str:
    values = _mapping_values(mapping, *keys)
    return values[0] if values else ""


def _mapping_values(mapping: dict[object, object], *keys: str) -> list[str]:
    normalized_keys = {key.casefold() for key in keys}
    values: list[str] = []
    for key, value in mapping.items():
        if isinstance(key, str) and key.casefold() in normalized_keys:
            values.extend(_text_values(value))

    extras = mapping.get("extras")
    for extra in _mapping_dicts(extras):
        extra_key = _text(extra.get("key") or extra.get("name")).casefold()
        if extra_key in normalized_keys:
            values.extend(_text_values(extra.get("value")))

    return _dedupe(values)


def _mapping_dicts(value: object) -> list[dict[object, object]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _value_text(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return _first_text_value(value)


def _country_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [
            country
            for country in (_text(part) for part in re.split(r"[;|]", value))
            if country
        ]
    if isinstance(value, dict):
        countries: list[str] = []
        for key in ("name", "addressCountry", "country", "address", "@value", "value"):
            countries.extend(_country_values(value.get(key)))
        return countries
    if isinstance(value, list):
        return [
            country
            for item in value
            for country in _country_values(item)
        ]

    return []


def _first_text(mapping: dict[object, object], *keys: str) -> str:
    for key in keys:
        value = _first_text_value(mapping.get(key))
        if value:
            return value

    return ""


def _first_text_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _first_text(value, "@value", "value", "name", "title")
    if isinstance(value, list):
        for item in value:
            text = _first_text_value(item)
            if text:
                return text

    return ""


def _text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        text = _first_text_value(value)
        return [text] if text else []
    if isinstance(value, list):
        return [
            text
            for item in value
            for text in [_first_text_value(item)]
            if text
        ]

    return []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _first_url(*values: object) -> str:
    for value in values:
        text = _first_text_value(value)
        if text:
            return text

    return ""


def _json_ld_type_matches(value: object, expected_type: str) -> bool:
    return any(
        item.rsplit(":", 1)[-1].lower() == expected_type.lower()
        for item in _text_values(value)
    )


def _site_root(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _normalize_format(value: str) -> str:
    if not value:
        return ""

    normalized = value.strip().upper()
    if normalized in {"N/A", "NA", "UNKNOWN"}:
        return ""

    return normalized


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
