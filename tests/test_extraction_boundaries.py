from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from collector.budget import CollectionBudgetExceeded, collection_budget
from collector.execution import ExecutionControl, ExecutionStopped, execution_control
from collector.extraction.errors import ExtractionError
from collector.extraction.extractor import (
    _PageHTMLParser,
    _TextHTMLParser,
    extract_page,
    html_to_text,
)
from collector.extraction.limits import DEFAULT_EXTRACTION_LIMITS

URL = "https://example.org/dataset"


def limits(**values):
    return replace(DEFAULT_EXTRACTION_LIMITS, **values)


def script(text):
    return f'<script type="application/ld+json">{text}</script>'


def test_nested_link_amplification_is_stopped_during_html_parsing():
    html = '<div><a href="/data.csv">Download</a>' * 4_000 + "</div>" * 4_000
    assert len(html) < 1_000_000
    with pytest.raises(ExtractionError, match="HTML nesting limit") as error:
        extract_page(URL, html)
    assert error.value.code == "extraction_limit_exceeded"


@pytest.mark.parametrize("html,bounds,reason", [
    ('<a href="/a.csv">A</a>' * 3, {"max_links": 2}, "link limit"),
    ("<p></p>" * 3, {"max_html_nodes": 2}, "node limit"),
    ('<a href="/data.csv">Download</a>' * 5, {"max_evidence_chars": 80}, "evidence size"),
    ('<div><a href="/data.csv">Download</a></div>', {"max_dom_path_chars": 3}, "path size"),
    ('<meta content="too long">', {"max_attribute_chars": 8}, "attribute size"),
    ("x" * 20, {"max_html_chars": 10}, "HTML size"),
    (script("{}") * 3, {"max_json_ld_scripts": 2}, "script limit"),
    (script('"123456"') * 2, {"max_json_ld_chars": 10}, "JSON-LD size"),
    (script("[" + ",".join("1" for _ in range(30)) + "]"),
     {"max_json_ld_nodes": 10}, "JSON-LD node"),
])
def test_extraction_limits_are_enforced_before_retaining_excess_evidence(html, bounds, reason):
    with pytest.raises(ExtractionError, match=reason) as error:
        extract_page(URL, html, limits=limits(**bounds))
    assert error.value.code == "extraction_limit_exceeded"


def test_void_tags_do_not_accumulate_false_depth():
    page = extract_page(URL, "<meta name=x>" * 200 + "<h1>Dataset</h1>",
                        limits=limits(max_html_depth=2))
    assert page.h1 == "Dataset"


def test_bounded_parsing_preserves_words_at_large_input_boundaries():
    text = "x" * 16_378 + "cancer"
    page = extract_page(URL, f"<p>{text}</p>")
    assert page.text == text
    assert html_to_text(f"<p>{text}</p>") == text


@pytest.mark.parametrize("html", [
    script('{"@type":"Dataset",}'),
    script('{"number": NaN}'),
    '<script type="application/ld+json">{"@type":"Dataset"}',
])
def test_malformed_content_has_a_controlled_extraction_error(html):
    with pytest.raises(ExtractionError) as error:
        extract_page(URL, html)
    assert error.value.code == "extraction_invalid_content"


@pytest.mark.parametrize("parser_type,html", [
    (_PageHTMLParser, "<p>Dataset</p>"),
    (_TextHTMLParser, '<meta name="description" content="&lt;p&gt;Dataset&lt;/p&gt;">'),
])
@pytest.mark.parametrize("failure", [
    AssertionError, NotImplementedError, RecursionError, ValueError,
])
def test_stdlib_parser_failures_are_normalized_independently_of_python_version(
    monkeypatch, parser_type, html, failure,
):
    def fail(*args, **kwargs):
        raise failure("Parser failed")

    monkeypatch.setattr(parser_type, "feed", fail)
    with pytest.raises(ExtractionError) as error:
        extract_page(URL, html)
    assert error.value.code == "extraction_invalid_content"


def test_standard_declarations_comments_and_cdata_remain_accepted():
    html = ('<!DOCTYPE html><!-- A legitimate comment -->'
            '<![CDATA[Non-HTML evidence]]><h1>Dataset</h1><a href="/data.csv">CSV</a>')
    page = extract_page(URL, html)
    assert page.h1 == "Dataset"
    assert [link.url for link in page.links] == ["https://example.org/data.csv"]


def test_deep_json_is_rejected_before_the_python_recursion_limit():
    with pytest.raises(ExtractionError, match="JSON-LD nesting limit") as error:
        extract_page(URL, script("[" * 1_100 + "0" + "]" * 1_100))
    assert error.value.code == "extraction_limit_exceeded"


def test_json_brackets_inside_escaped_strings_do_not_consume_nesting():
    page = extract_page(URL, script('{"@type":"Dataset","name":"[\\\"[[]"}'),
                        limits=limits(max_json_ld_depth=4))
    assert page.dataset_json_ld[0]["name"] == '["[[]'


def test_malformed_link_does_not_discard_valid_links():
    page = extract_page(URL, '<a href="http://[bad">Bad</a><a href="/data.csv">CSV</a>')
    assert [link.url for link in page.links] == ["https://example.org/data.csv"]


def test_expired_budget_propagates_without_becoming_a_parse_failure():
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    with collection_budget(deadline_at=expired), pytest.raises(CollectionBudgetExceeded):
        extract_page(URL, "<p>Data</p>")


def test_cancellation_during_parsing_stops_before_more_evidence(monkeypatch):
    control = ExecutionControl()
    original = _PageHTMLParser.handle_starttag
    calls = []

    def start(parser, tag, attrs):
        calls.append(tag)
        original(parser, tag, attrs)
        if len(calls) == 3:
            control.abort()

    monkeypatch.setattr(_PageHTMLParser, "handle_starttag", start)
    token = execution_control.set(control)
    try:
        with pytest.raises(ExecutionStopped):
            extract_page(URL, "<p>Data</p>" * 100)
    finally:
        execution_control.reset(token)
    assert len(calls) == 3


def test_inline_html_metadata_uses_the_same_depth_boundary():
    with pytest.raises(ExtractionError, match="HTML nesting limit"):
        html_to_text("<div>" * 100 + "Data", limits=limits(max_html_depth=8))
