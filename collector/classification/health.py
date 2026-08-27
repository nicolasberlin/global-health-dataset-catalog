from __future__ import annotations

import re

from collector.extraction.dataset_metadata import dataset_metadata_text
from collector.storage.models import HealthClassification, HealthLabel, PageSnapshot

HEALTH_KEYWORDS = {
    "cancer",
    "clinical",
    "disease",
    "diagnosis",
    "epidemiology",
    "health",
    "healthcare",
    "hospital",
    "malaria",
    "maladie",
    "medical",
    "mental health",
    "morbidity",
    "morbidite",
    "mortality",
    "mortalite",
    "patient",
    "sante",
    "treatment",
    "vaccination",
}


def score_health_page(page: PageSnapshot) -> HealthClassification:
    extracted_metadata = dataset_metadata_text(page.dataset_metadata())
    title_surface = _normalize(
        " ".join([page.title, page.h1, page.meta_description])
    )
    body_surface = _normalize(
        " ".join([extracted_metadata, page.publisher, page.text[:8000], page.canonical_url])
    )

    title_hits = _matched_keywords(title_surface)
    body_hits = _matched_keywords(body_surface)
    matched_keywords = sorted(set(title_hits + body_hits))

    score = 0.0
    if title_hits:
        score += min(0.55, len(set(title_hits)) * 0.35)
    if body_hits:
        score += min(0.45, len(set(body_hits)) * 0.08)
    if _publisher_health_signal(page.publisher):
        score += 0.2

    probability = min(score, 1.0)
    return HealthClassification(
        probability=probability,
        label=_label_for_probability(probability),
        signals={
            "matched_keywords": matched_keywords,
            "title_keyword_count": len(set(title_hits)),
            "body_keyword_count": len(set(body_hits)),
            "publisher_health_signal": _publisher_health_signal(page.publisher),
        },
    )
def _matched_keywords(surface: str) -> list[str]:
    matches: list[str] = []
    for keyword in HEALTH_KEYWORDS:
        normalized_keyword = _normalize(keyword)
        if re.search(rf"\b{re.escape(normalized_keyword)}\b", surface):
            matches.append(keyword)
    return matches


def _publisher_health_signal(publisher: str) -> bool:
    normalized = _normalize(publisher)
    return bool(re.search(r"\b(health|sante|hospital|ministry of health)\b", normalized))


def _label_for_probability(probability: float) -> HealthLabel:
    if probability >= 0.75:
        return "HEALTH"
    if probability >= 0.35:
        return "PARTIALLY_HEALTH"
    return "NON_HEALTH"


def _normalize(value: str) -> str:
    replacements = str.maketrans({"é": "e", "è": "e", "ê": "e", "à": "a", "ô": "o"})
    return value.lower().translate(replacements)
