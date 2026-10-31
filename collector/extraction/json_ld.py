"""Read metadata fields from the selected local JSON-LD dataset evidence."""

from __future__ import annotations

from collector.extraction.dataset_metadata import (
    _country_values,
    _dedupe,
    _modalities_from_text,
)
from collector.extraction.limits import json_objects
from collector.extraction.text import _normalize_text
from collector.storage.metadata import normalize_doi


def _publisher_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _root_objects(json_ld_items):
        publisher = item.get("publisher")
        if isinstance(publisher, dict):
            name = publisher.get("name")
            if isinstance(name, str) and name.strip():
                return _normalize_text(name)
        if isinstance(publisher, str) and publisher.strip():
            return _normalize_text(publisher)

    return ""


def _geography_from_json_ld(json_ld_items: list[object]) -> list[str]:
    geography: list[str] = []
    for item in _root_objects(json_ld_items):
        for key in (
            "spatialCoverage",
            "spatial",
            "areaServed",
            "contentLocation",
            "locationCreated",
            "countryOfOrigin",
            "coverage",
            "dct:coverage",
            "dct:spatial",
        ):
            geography.extend(_country_values(item.get(key)))

    return _dedupe(geography)


def _date_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _root_objects(json_ld_items):
        for key in ("datePublished", "publicationDate", "dct:issued", "issued"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)

    return ""


def _license_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _root_objects(json_ld_items):
        value = item.get("license")
        if isinstance(value, str) and value.strip():
            return _normalize_text(value)
        if isinstance(value, dict):
            for key in ("name", "url", "@id"):
                nested_value = value.get(key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return _normalize_text(nested_value)

    return ""


def _size_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _root_objects(json_ld_items):
        for key in ("size", "contentSize", "content_size"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)

    return ""


def _modalities_from_json_ld(json_ld_items: list[object]) -> list[str]:
    values: list[str] = []
    for item in _root_objects(json_ld_items):
        for key in ("encodingFormat", "fileFormat", "format"):
            value = item.get(key)
            if isinstance(value, str):
                values.extend(_modalities_from_text(value))
        distribution = item.get("distribution")
        if isinstance(distribution, (dict, list)):
            for distribution_item in _iter_json_objects(distribution):
                for key in ("encodingFormat", "fileFormat", "contentUrl"):
                    value = distribution_item.get(key)
                    if isinstance(value, str):
                        values.extend(_modalities_from_text(value))

    return _dedupe(values)


def _iter_json_objects(value: object) -> list[dict[str, object]]:
    return list(json_objects(value))


def _root_objects(value: list[object]):
    return (item for item in value if isinstance(item, dict))


def _doi_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _root_objects(json_ld_items):
        types = item.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if not isinstance(types, list):
            continue
        if not any(str(value).rsplit("/", 1)[-1].rsplit(":", 1)[-1] == "Dataset"
                   for value in types):
            continue
        identifiers = item.get("identifier", [])
        if not isinstance(identifiers, list):
            identifiers = [identifiers]
        for identifier in [item.get("@id"), *identifiers]:
            if isinstance(identifier, dict):
                identifier = identifier.get("value") or identifier.get("@id")
            doi = normalize_doi(identifier)
            if doi:
                return doi
    return ""
