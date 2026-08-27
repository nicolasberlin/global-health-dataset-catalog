from __future__ import annotations

import json
import re
import unicodedata

from collector.extraction.dataset_metadata import dataset_metadata_text
from collector.extraction.distributions import extract_distributions
from collector.storage.models import ClassificationResult, DistributionCandidate, PageSnapshot

INDIVIDUAL_DATASET_CONCEPTS = {
    "dataset": (r"\bdataset\b", r"\bdata set\b", r"\bjeu de donnees\b"),
    "indicator": (r"\bindicator\b",),
    "statistics": (r"\bstatistics\b",),
}

CATALOG_CONCEPTS = {
    "catalog": (r"\bcatalog(?:ue)?\b",),
    "data_portal": (r"\bdata portal\b",),
    "datasets": (r"\bdatasets\b",),
    "indicators": (r"\bindicators\b",),
    "open_data": (r"\bopen data\b",),
}

ACCESS_CONCEPTS = {
    "api": (r"\bapi\b",),
    "csv": (r"\bcsv\b",),
    "download_data": (r"\bdownload data\b",),
    "downloads": (r"\bdownloads?\b",),
    "export": (r"\bexport\b",),
    "resources": (r"\bresources?\b",),
    "xlsx": (r"\bxlsx\b",),
}


def score_dataset_page(
    page: PageSnapshot,
    distributions: list[DistributionCandidate] | None = None,
) -> ClassificationResult:
    distributions = distributions if distributions is not None else extract_distributions(page)
    surfaces = _page_surfaces(page)
    full_surface = " ".join(surfaces.values())
    signals: dict[str, object] = {}
    dataset_evidence = 0.0
    access_evidence = 0.0
    context_evidence = 0.0
    has_individual_dataset_evidence = False

    if _has_jsonld_type(page.json_ld, "dataset"):
        dataset_evidence += 0.65
        has_individual_dataset_evidence = True
        signals["schema_dataset"] = True

    if "dcat:dataset" in full_surface:
        dataset_evidence += 0.6
        has_individual_dataset_evidence = True
        signals["dcat_dataset"] = True

    if "dcat:distribution" in full_surface:
        access_evidence += 0.1
        signals["dcat_distribution"] = True

    title_dataset_concepts = _matched_concepts(
        surfaces["title"],
        INDIVIDUAL_DATASET_CONCEPTS,
    )
    if title_dataset_concepts:
        dataset_evidence += min(0.5, 0.32 + len(title_dataset_concepts) * 0.08)
        has_individual_dataset_evidence = True
        signals["title_dataset_concepts"] = title_dataset_concepts

    metadata_dataset_concepts = _matched_concepts(
        surfaces["metadata"],
        INDIVIDUAL_DATASET_CONCEPTS,
    )
    if metadata_dataset_concepts:
        dataset_evidence += min(0.2, len(metadata_dataset_concepts) * 0.08)
        signals["metadata_dataset_concepts"] = metadata_dataset_concepts

    body_dataset_concepts = _matched_concepts(
        surfaces["body"],
        INDIVIDUAL_DATASET_CONCEPTS,
    )
    if body_dataset_concepts:
        dataset_evidence += min(0.16, len(body_dataset_concepts) * 0.06)
        signals["body_dataset_concepts"] = body_dataset_concepts

    catalog_concepts = _matched_concepts(full_surface, CATALOG_CONCEPTS)
    if catalog_concepts:
        context_evidence += min(0.1, len(catalog_concepts) * 0.035)
        signals["catalog_concepts"] = catalog_concepts

    access_concepts = _matched_concepts(full_surface, ACCESS_CONCEPTS)
    if access_concepts:
        access_evidence += min(0.16, len(access_concepts) * 0.04)
        signals["access_concepts"] = access_concepts

    if distributions:
        access_evidence += min(0.22, len(distributions) * 0.1)
        signals["direct_distribution_count"] = len(distributions)

    score = dataset_evidence + access_evidence + context_evidence
    if not has_individual_dataset_evidence:
        score = min(score, 0.5)

    probability = min(score, 1.0)
    signals["dataset_evidence_score"] = round(dataset_evidence, 3)
    signals["access_evidence_score"] = round(access_evidence, 3)
    signals["accepted_by_heuristics"] = probability >= 0.6
    return ClassificationResult(probability=probability, signals=signals)


def _page_surfaces(page: PageSnapshot) -> dict[str, str]:
    extracted_metadata = dataset_metadata_text(page.dataset_metadata())
    return {
        "title": _normalize_surface(
            " ".join([page.title, page.h1, page.og_title])
        ),
        "metadata": _normalize_surface(
            " ".join([extracted_metadata, page.meta_description, page.og_description])
        ),
        "body": _normalize_surface(
            " ".join([page.url, page.canonical_url, " ".join(page.headings), page.text[:5000]])
        ),
    }
def _has_jsonld_type(json_ld: tuple[object, ...], expected_type: str) -> bool:
    for node in _iter_json_objects(json_ld):
        type_value = node.get("@type") or node.get("type")
        if isinstance(type_value, str) and _type_matches(type_value, expected_type):
            return True
        if isinstance(type_value, list) and any(
            _type_matches(str(item), expected_type)
            for item in type_value
        ):
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


def _matched_concepts(
    surface: str,
    concepts: dict[str, tuple[str, ...]],
) -> list[str]:
    return sorted(
        concept
        for concept, patterns in concepts.items()
        if any(re.search(pattern, surface) for pattern in patterns)
    )


def _normalize_surface(value: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def _type_matches(type_value: str, expected_type: str) -> bool:
    normalized_type = type_value.strip().lower().rstrip("/#")
    local_name = re.split(r"[/#]", normalized_type)[-1]
    return local_name == expected_type or local_name.endswith(f":{expected_type}")
