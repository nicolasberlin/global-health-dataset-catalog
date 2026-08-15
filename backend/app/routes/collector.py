from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from collector.classification.dataset import score_dataset_page
from collector.classification.health import score_health_page
from collector.config import DEFAULT_CONFIG
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.fetch import fetch_public_html

router = APIRouter(prefix="/collector", tags=["collector"])


class CollectorAnalyzeHTMLRequest(BaseModel):
    url: HttpUrl
    html: str = Field(min_length=1)


class CollectorAnalyzeURLRequest(BaseModel):
    url: HttpUrl


class CollectorDistribution(BaseModel):
    url: str
    format: str
    probability: float
    anchor: str = ""
    mime_type: str = ""


class CollectorAnalyzeHTMLResponse(BaseModel):
    accepted: bool
    dataset_url: str
    title: str
    description: str
    publisher: str
    dataset_probability: float
    dataset_signals: dict[str, Any]
    health_probability: float
    health_label: str
    health_signals: dict[str, Any]
    distributions: list[CollectorDistribution]


@router.post("/analyze-html")
def analyze_html(payload: CollectorAnalyzeHTMLRequest) -> CollectorAnalyzeHTMLResponse:
    return _analyze_html(str(payload.url), payload.html)


@router.post("/analyze-url")
def analyze_url(payload: CollectorAnalyzeURLRequest) -> CollectorAnalyzeHTMLResponse:
    try:
        fetched_page = fetch_public_html(str(payload.url))
    except ValueError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return _analyze_html(fetched_page.final_url, fetched_page.html)


def _analyze_html(url: str, html: str) -> CollectorAnalyzeHTMLResponse:
    page = extract_page(url, html)
    distributions = extract_distributions(page)
    dataset_score = score_dataset_page(page, distributions)
    health_score = score_health_page(page)
    accepted = (
        dataset_score.probability >= DEFAULT_CONFIG.min_dataset_probability
        and health_score.probability >= DEFAULT_CONFIG.min_health_probability
    )

    return CollectorAnalyzeHTMLResponse(
        accepted=accepted,
        dataset_url=page.canonical_url,
        title=page.title or page.h1 or page.canonical_url,
        description=page.meta_description or page.og_description,
        publisher=page.publisher,
        dataset_probability=dataset_score.probability,
        dataset_signals=dataset_score.signals,
        health_probability=health_score.probability,
        health_label=health_score.label,
        health_signals=health_score.signals,
        distributions=[
            CollectorDistribution(
                url=distribution.url,
                format=distribution.format,
                probability=distribution.probability,
                anchor=distribution.anchor,
                mime_type=distribution.mime_type,
            )
            for distribution in distributions
        ],
    )
