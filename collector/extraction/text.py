"""Bounded HTML parsing primitives and conversion to normalized plain text."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

from collector.budget import check_collection_budget
from collector.extraction.errors import ExtractionError
from collector.extraction.limits import (
    DEFAULT_EXTRACTION_LIMITS,
    ExtractionLimits,
    enforce_limit,
)

SKIP_TEXT_TAGS = {"script", "style", "noscript", "svg"}


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "param", "source", "track", "wbr"}


class _BoundedHTMLParser(HTMLParser):
    def __init__(self, limits: ExtractionLimits) -> None:
        super().__init__(convert_charrefs=True)
        self.limits = limits
        self.stack: list[str] = []
        self.nodes = self.evidence_chars = 0

    def _node(self) -> None:
        check_collection_budget()
        self.nodes += 1
        enforce_limit(self.nodes, self.limits.max_html_nodes, "HTML node limit exceeded.")

    def _retain(self, text: str) -> str:
        self.evidence_chars += len(text)
        enforce_limit(self.evidence_chars, self.limits.max_evidence_chars,
                      "Extraction evidence size limit exceeded.")
        return text

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._node()
        for name, value in attrs:
            enforce_limit(len(name) + len(value or ""), self.limits.max_attribute_chars,
                          "HTML attribute size limit exceeded.")
            self._retain(name + (value or ""))
        if tag not in VOID_TAGS:
            enforce_limit(len(self.stack) + 1, self.limits.max_html_depth,
                          "HTML nesting limit exceeded.")
            self.stack.append(tag)

    def _end(self, tag: str) -> None:
        check_collection_budget()
        if tag in self.stack:
            last_index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[last_index:]

    def handle_decl(self, decl: str) -> None:
        self._node()

    def handle_comment(self, data: str) -> None:
        self._node()

    def unknown_decl(self, data: str) -> None:
        # Declarations are not dataset evidence. HTMLParser versions differ in
        # which malformed declarations they ignore or reject before this hook.
        self._node()


def _feed_html(parser: _BoundedHTMLParser, html: str) -> None:
    enforce_limit(len(html), parser.limits.max_html_chars, "HTML size limit exceeded.")
    try:
        check_collection_budget()
        # Callbacks check the budget per node. Splitting feed arbitrarily also
        # splits text tokens, which would insert spaces inside words downstream.
        parser.feed(html)
        parser.close()
        check_collection_budget()
    except ExtractionError:
        raise
    except (AssertionError, NotImplementedError, RecursionError, ValueError) as error:
        raise ExtractionError("HTML content could not be parsed.") from error


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def html_to_text(value: str, *, limits: ExtractionLimits = DEFAULT_EXTRACTION_LIMITS) -> str:
    enforce_limit(len(value), limits.max_html_chars, "HTML text size limit exceeded.")
    check_collection_budget()
    if "<" not in value and "&" not in value:
        enforce_limit(len(value), limits.max_evidence_chars, "HTML text evidence limit exceeded.")
        return _normalize_text(value)

    parser = _TextHTMLParser(limits)
    _feed_html(parser, unescape(value))
    return _normalize_text(" ".join(parser.text_parts))


class _TextHTMLParser(_BoundedHTMLParser):
    def __init__(self, limits: ExtractionLimits) -> None:
        super().__init__(limits)
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag.lower(), attrs)

    def handle_endtag(self, tag: str) -> None:
        self._end(tag.lower())

    def handle_data(self, data: str) -> None:
        self._node()
        if any(tag in SKIP_TEXT_TAGS for tag in self.stack):
            return

        text = _normalize_text(data)
        if text:
            self.text_parts.append(self._retain(text))
