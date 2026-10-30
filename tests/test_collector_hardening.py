"""Public collector boundaries preserve fallback, identity and proven resources."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from collector.budget import check_collection_budget
from collector.classification.page import PageClassification, PageClassificationError
from collector.classification.page_llm_classifier import LLMPageClassifier
from collector.collection.contracts import StrategyResult
from collector.collection.service import (
    collect_repository_candidate_with_report,
    collect_source_with_report,
)
from collector.config import CollectorConfig
from collector.discovery.adapters.shared import DiscoveredPage
from collector.extraction.distributions import extract_distributions
from collector.extraction.extractor import extract_page
from collector.network.fetch import FetchedPage
from collector.storage.models import PageSnapshot, ValidationResult

URL = "https://example.org/health/record"
HTML = '<title>Health dataset</title><a href="/data.csv">Download CSV</a>'
DEEP_HTML = "<div>" * 150 + HTML + "</div>" * 150


class Accept:
    def classify(self, page, distributions):
        return PageClassification(True)


def available(resource):
    return ValidationResult(resource.url, resource.url, "CSV", True, 200, mime_type="text/csv")


def fetched(url, html):
    return FetchedPage(url, url, html, 200, "text/html")


class Browser:
    def __init__(self):
        self.calls = []

    def render(self, url, *, metadata_url=None):
        self.calls.append("render")
        return StrategyResult(DiscoveredPage(url, "browser"), html=HTML, http_status=200)

    def validate(self, resource):
        self.calls.append("validate")
        return available(resource)


@pytest.mark.parametrize("html,code", [
    (DEEP_HTML, "extraction_limit_exceeded"),
    ('<script type="application/ld+json">{"@type":"Dataset",}</script>',
     "extraction_invalid_content"),
])
def test_bad_extraction_automatically_uses_browser_and_preserves_failure_history(html, code):
    browser = Browser()
    result = collect_repository_candidate_with_report(
        URL, fetch_html=lambda url: fetched(url, html), classifier=Accept(), browser=browser,
        validate=lambda _: pytest.fail("Browser-bound resource must use its own session"),
    )
    assert len(result.datasets) == 1 and not result.report.errors
    assert result.report.verification_complete
    assert browser.calls == ["render", "validate"]
    assert [(attempt["method"], attempt["status"], attempt["code"])
            for attempt in result.report.method_attempts] == [
        ("html", "failed", code), ("browser", "succeeded", ""),
    ]


def test_no_available_fallback_is_incomplete_instead_of_semantic_rejection():
    result = collect_repository_candidate_with_report(
        URL, fetch_html=lambda url: fetched(url, DEEP_HTML), classifier=Accept(),
    )
    assert not result.datasets and not result.report.verification_complete
    assert result.report.rejected_count == 0
    assert [error.code for error in result.report.errors] == ["extraction_limit_exceeded"]


def test_source_uses_configured_fallback_after_extraction_limit():
    browser = Browser()
    result = collect_source_with_report(
        URL, discover=lambda _: [DiscoveredPage(URL, "generic")],
        fetch_html=lambda url: fetched(url, DEEP_HTML), classifier=Accept(), browser=browser,
    )
    assert len(result.datasets) == 1 and not result.report.errors
    assert browser.calls == ["render", "validate"]


def test_bad_source_page_does_not_discard_other_datasets_or_become_a_rejection():
    good_url = URL + "/good"
    result = collect_source_with_report(
        URL, discover=lambda _: [
            DiscoveredPage(URL, "generic"), DiscoveredPage(good_url, "generic"),
        ],
        fetch_html=lambda url: fetched(url, DEEP_HTML if url == URL else HTML),
        classifier=Accept(), validate=available,
    )
    assert [dataset.dataset_url for dataset in result.datasets] == [good_url]
    assert result.report.analyzed_count == 2 and result.report.rejected_count == 0
    assert not result.report.verification_complete
    assert [error.code for error in result.report.errors] == ["extraction_limit_exceeded"]


def test_nested_model_signal_is_rejected_without_recursively_copying_it():
    nested = []
    for _ in range(2_000):
        nested = [nested]

    class Client:
        def classify_page(self, payload):
            return {"accepted": True, "dataset_signals": {"reason": "Dataset", "evidence": nested}}

    with pytest.raises(PageClassificationError) as caught:
        LLMPageClassifier(Client()).classify(PageSnapshot(URL, URL), [])
    assert caught.value.diagnostics[0].code == "llm_invalid_response"


def test_embedded_dataset_type_with_full_fragment_iri_keeps_its_metadata_and_scope():
    graph = {"@graph": [
        {"@type": "WebPage", "license": "Site Terms"},
        {"@type": "http://www.w3.org/ns/dcat#Dataset", "@id": URL, "license": "CC0",
         "distribution": {"contentUrl": "/data.csv", "encodingFormat": "text/csv"}},
    ]}
    page = extract_page(
        URL, '<script type="application/ld+json">' + json.dumps(graph) + "</script>",
    )
    assert page.sharing_license == "CC0"
    assert [resource.url for resource in extract_distributions(page)] == [
        "https://example.org/data.csv",
    ]


def test_html_is_parsed_once_before_classification(monkeypatch):
    from collector.collection import pipeline

    real_extract = pipeline.extract_page
    parsed = []

    def extract(*args, **kwargs):
        parsed.append(args[0])
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_page", extract)
    result = collect_repository_candidate_with_report(
        URL, fetch_html=lambda url: fetched(url, HTML), classifier=Accept(), validate=available,
    )
    assert len(result.datasets) == 1
    assert parsed == [URL]


def test_ambiguous_graph_is_incomplete_and_does_not_guess_a_dataset():
    graph = {"@graph": [
        {"@type": "Dataset", "@id": "https://example.org/a", "license": "CC0"},
        {"@type": "Dataset", "@id": "https://example.org/b", "license": "CC-BY"},
    ]}
    html = HTML + '<script type="application/ld+json">' + json.dumps(graph) + "</script>"
    result = collect_repository_candidate_with_report(
        URL, fetch_html=lambda url: fetched(url, html), classifier=Accept(),
        validate=lambda _: pytest.fail("Unscoped resources must not be associated"),
    )
    assert not result.datasets and result.report.rejected_count == 0
    assert [error.code for error in result.report.errors] == ["dataset_identity_ambiguous"]


@pytest.mark.parametrize("source_fallback", [False, True])
def test_collection_keeps_proven_links_when_a_later_probe_exhausts_budget(
    monkeypatch, source_fallback,
):
    clock = [0.0]
    monkeypatch.setattr("collector.budget.monotonic", lambda: clock[0])
    calls = []

    def validate(resource):
        calls.append(resource.url)
        if len(calls) == 2:
            clock[0] += 5
            check_collection_budget()
        return replace(available(resource), format="JSON", mime_type="application/json")

    expanded = HTML + '<a href="/other.csv">Download CSV</a>'
    options = {
        "config": CollectorConfig(collection_max_duration_seconds=5, max_distributions_saved=3),
        "classifier": Accept(), "validate": validate,
    }
    if source_fallback:
        class PartialBrowser(Browser):
            def render(self, url, *, metadata_url=None):
                return StrategyResult(
                    DiscoveredPage(url, "browser"), html=expanded, http_status=200,
                )

            def validate(self, resource):
                return validate(resource)

        result = collect_source_with_report(
            URL, discover=lambda _: [DiscoveredPage(URL, "generic")],
            fetch_html=lambda url: fetched(url, DEEP_HTML), browser=PartialBrowser(), **options,
        )
    else:
        result = collect_repository_candidate_with_report(
            URL, fetch_html=lambda url: fetched(url, expanded), **options,
        )
    assert len(calls) == 2 and len(result.datasets) == 1
    dataset = result.datasets[0]
    assert len(dataset.distributions) == len(dataset.validation_results) == 1
    assert dataset.distributions[0].format == "JSON"
    assert dataset.distributions[0].mime_type == "application/json"
    assert [error.code for error in result.report.errors] == ["collection_budget_exhausted"]
    assert not result.report.verification_complete
