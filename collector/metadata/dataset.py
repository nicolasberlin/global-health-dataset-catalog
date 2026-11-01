"""Normalize dataset fields and infer metadata from bounded page text."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from collector.parsing.html_text import _normalize_text, html_to_text

DATASET_METADATA_KEYS = (
    "Title",
    "Geography",
    "Date of publication",
    "Dataset URL",
    "Disease(s)",
    "Size of dataset",
    "Demographic information",
    "Sharing license",
    "Modality of data",
    "Description of dataset",
)
MISSING_DATASET_METADATA_VALUE = "NA"


def normalize_dataset_metadata(
    metadata: Mapping[str, object] | None,
) -> dict[str, str]:
    metadata = metadata or {}
    return {
        key: _value(metadata.get(key, ""))
        for key in DATASET_METADATA_KEYS
    }


def build_dataset_metadata(
    *,
    title: str = "",
    geography: Iterable[str] = (),
    date_of_publication: str = "",
    dataset_url: str = "",
    diseases: Iterable[str] = (),
    size_of_dataset: str = "",
    demographic_information: Iterable[str] = (),
    sharing_license: str = "",
    modality_of_data: Iterable[str] = (),
    description_of_dataset: str = "",
) -> dict[str, str]:
    return normalize_dataset_metadata(
        {
            "Title": title,
            "Geography": _values(geography),
            "Date of publication": date_of_publication,
            "Dataset URL": dataset_url,
            "Disease(s)": _values(diseases),
            "Size of dataset": size_of_dataset,
            "Demographic information": _values(demographic_information),
            "Sharing license": sharing_license,
            "Modality of data": _values(modality_of_data),
            "Description of dataset": description_of_dataset,
        }
    )


def _value(value: object) -> str:
    if value is None:
        return MISSING_DATASET_METADATA_VALUE

    normalized_value = str(value).strip()
    return normalized_value if normalized_value else MISSING_DATASET_METADATA_VALUE


def _values(values: Iterable[str]) -> str:
    normalized_values = []
    for value in values:
        normalized_value = value.strip()
        if normalized_value and normalized_value not in normalized_values:
            normalized_values.append(normalized_value)

    return ", ".join(normalized_values) if normalized_values else MISSING_DATASET_METADATA_VALUE


def _diseases_from_text(value: str) -> list[str]:
    disease_terms = (
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
    normalized = value.lower()
    return [term for term in disease_terms if re.search(rf"\b{re.escape(term)}\b", normalized)]


def _demographics_from_text(value: str) -> list[str]:
    demographic_terms = ("age", "sex", "gender", "height", "weight")
    normalized = value.lower()
    return [
        term
        for term in demographic_terms
        if re.search(rf"\b{re.escape(term)}\b", normalized)
    ]


def _modalities_from_text(value: str) -> list[str]:
    normalized = value.lower()
    modality_by_term = {
        "csv": "tabular",
        "xlsx": "tabular",
        "xls": "tabular",
        "json": "structured data",
        "text": "text",
        "image": "images",
        "audio": "speech/audio",
        "speech": "speech",
    }
    return [
        modality
        for term, modality in modality_by_term.items()
        if re.search(rf"\b{re.escape(term)}\b", normalized)
        and not (
            term == "text"
            and re.search(r"\btext/(?:csv|tab-separated-values)\b", normalized)
        )
    ]


def _country_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [
            country
            for country in (
                _normalize_text(part) for part in re.split(r"[;|]", html_to_text(value))
            )
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


def _metadata_text(value: object) -> str:
    return html_to_text(value) if isinstance(value, str) else ""


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
