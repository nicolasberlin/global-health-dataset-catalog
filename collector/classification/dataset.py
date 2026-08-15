from __future__ import annotations

import json

from collector.extraction.distributions import extract_distributions
from collector.storage.models import ClassificationResult, DistributionCandidate, PageSnapshot

DATASET_TERMS = {
    "catalog",
    "catalogue",
    "data portal",
    "dataset",
    "datasets",
    "indicator",
    "indicators",
    "jeu de donnees",
    "open data",
    "statistics",
}

DOWNLOAD_TERMS = {
    "api",
    "csv",
    "download data",
    "downloads",
    "export",
    "resources",
    "xlsx",
}


def score_dataset_page(
    page: PageSnapshot,
    distributions: list[DistributionCandidate] | None = None,
) -> ClassificationResult:
    distributions = distributions if distributions is not None else extract_distributions(page)
    surface = _page_surface(page)
    signals: dict[str, object] = {}
    score = 0.0

    if _has_jsonld_type(page.json_ld, "dataset"):
        score += 0.7
        signals["schema_dataset"] = True

    if "dcat:dataset" in surface or "dcat:distribution" in surface:
        score += 0.55
        signals["dcat_signal"] = True

    dataset_terms = sorted(term for term in DATASET_TERMS if term in surface)
    if dataset_terms:
        score += min(0.28, len(dataset_terms) * 0.07)
        signals["dataset_terms"] = dataset_terms

    download_terms = sorted(term for term in DOWNLOAD_TERMS if term in surface)
    if download_terms:
        score += min(0.22, len(download_terms) * 0.055)
        signals["download_terms"] = download_terms

    if distributions:
        score += min(0.4, len(distributions) * 0.16)
        signals["direct_distribution_count"] = len(distributions)

    probability = min(score, 1.0)
    signals["accepted_by_heuristics"] = probability >= 0.6
    return ClassificationResult(probability=probability, signals=signals)


def _page_surface(page: PageSnapshot) -> str:
    return " ".join(
        [
            page.url,
            page.canonical_url,
            page.title,
            page.h1,
            page.meta_description,
            page.og_title,
            page.og_description,
            " ".join(page.headings),
            page.text[:5000],
        ]
    ).lower()


def _has_jsonld_type(json_ld: tuple[object, ...], expected_type: str) -> bool:
    for node in _iter_json_objects(json_ld):
        type_value = node.get("@type") or node.get("type")
        if isinstance(type_value, str) and type_value.lower() == expected_type:
            return True
        if isinstance(type_value, list) and expected_type in {
            str(item).lower() for item in type_value
        }:
            return True

    return False


def _iter_json_objects(value: object) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []

    if isinstance(value, dict):
        objects.append(value)
        for nested in value.values():
            objects.extend(_iter_json_objects(nested))
    elif isinstance(value, (list, tuple)):
        for item in value:
            objects.extend(_iter_json_objects(item))
    elif isinstance(value, str):
        try:
            objects.extend(_iter_json_objects(json.loads(value)))
        except json.JSONDecodeError:
            pass

    return objects

