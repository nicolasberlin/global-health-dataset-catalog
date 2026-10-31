"""Extract page structure, links, HTML metadata and raw JSON-LD evidence."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from collector.extraction.dataset_metadata import _country_values
from collector.extraction.limits import ExtractionLimits, enforce_limit, load_json_ld
from collector.extraction.text import (
    SKIP_TEXT_TAGS,
    _BoundedHTMLParser,
    _normalize_text,
    html_to_text,
)
from collector.storage.metadata import normalize_doi
from collector.storage.models import LinkCandidate
from collector.url_utils import canonicalize_url, same_domain

BLOCKED_LINK_SCHEMES = {"mailto", "tel", "javascript"}


class _PageHTMLParser(_BoundedHTMLParser):
    def __init__(self, url: str, limits: ExtractionLimits) -> None:
        super().__init__(limits)
        self.url = url
        self.stack: list[str] = []
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[LinkCandidate] = []
        self.json_ld: list[object] = []
        self.canonical_href = ""
        self.meta_description = ""
        self.og_title = ""
        self.og_description = ""
        self.publisher = ""
        self.doi = ""
        self.geography: list[str] = []
        self._active_link: dict[str, object] | None = None
        self._active_json_ld_parts: list[str] | None = None
        self._json_ld_chars = self._json_ld_scripts = self._link_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._start(tag, attrs)
        attributes = {name.lower(): value or "" for name, value in attrs}

        if tag == "link":
            rel = attributes.get("rel", "").lower()
            href = attributes.get("href", "")
            if "canonical" in rel and href:
                self.canonical_href = href.strip()

        if tag == "meta":
            self._handle_meta(attributes)

        if tag == "a" and attributes.get("href"):
            href = attributes["href"].strip()
            self._link_count += 1
            enforce_limit(self._link_count, self.limits.max_links, "HTML link limit exceeded.")
            try:
                scheme = urlsplit(href).scheme.lower()
            except ValueError:
                return  # A malformed link must not discard unrelated usable evidence.
            if scheme not in BLOCKED_LINK_SCHEMES:
                resolved_url = canonicalize_url(href, self.url)
                path_size = sum(len(part) + 1 for part in self.stack)
                enforce_limit(path_size, self.limits.max_dom_path_chars,
                              "HTML link path size limit exceeded.")
                self._active_link = {
                    "url": resolved_url,
                    "anchor_parts": [],
                    "dom_path": self._retain("/".join(self.stack)),
                }

        if tag == "script" and "ld+json" in attributes.get("type", "").lower():
            self._json_ld_scripts += 1
            enforce_limit(self._json_ld_scripts, self.limits.max_json_ld_scripts,
                          "JSON-LD script limit exceeded.")
            self._active_json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "a" and self._active_link is not None:
            anchor = _normalize_text(" ".join(self._active_link["anchor_parts"]))
            url = str(self._active_link["url"])
            self.links.append(
                LinkCandidate(
                    url=url,
                    anchor=anchor,
                    nearby_text=anchor,
                    extension=_url_extension(url),
                    same_domain=same_domain(self.url, url),
                    dom_path=str(self._active_link["dom_path"]),
                )
            )
            self._active_link = None

        if tag == "script" and self._active_json_ld_parts is not None:
            self._parse_json_ld("".join(self._active_json_ld_parts))
            self._active_json_ld_parts = None

        self._end(tag)

    def handle_data(self, data: str) -> None:
        self._node()
        if self._active_json_ld_parts is not None:
            self._json_ld_chars += len(data)
            enforce_limit(self._json_ld_chars, self.limits.max_json_ld_chars,
                          "JSON-LD size limit exceeded.")
            self._active_json_ld_parts.append(data)
            return

        text = _normalize_text(data)
        if not text:
            return

        if self._active_link is not None:
            self._active_link["anchor_parts"].append(self._retain(text))

        if "title" in self.stack:
            self.title_parts.append(self._retain(text))

        if "h1" in self.stack:
            self.h1_parts.append(self._retain(text))

        if self.stack and self.stack[-1] in {"h2", "h3"}:
            self.heading_parts.append(self._retain(text))

        if not any(tag in SKIP_TEXT_TAGS for tag in self.stack):
            self.text_parts.append(self._retain(text))

    def _handle_meta(self, attributes: dict[str, str]) -> None:
        name = attributes.get("name", "").lower()
        property_name = attributes.get("property", "").lower()
        itemprop = attributes.get("itemprop", "").lower()
        content = html_to_text(attributes.get("content", ""), limits=self.limits)

        if not content:
            return

        if name == "citation_doi":
            self.doi = normalize_doi(content)

        if name == "description" and not self.meta_description:
            self.meta_description = content
        elif property_name == "og:title" and not self.og_title:
            self.og_title = content
        elif property_name == "og:description" and not self.og_description:
            self.og_description = content
        elif name in {"publisher", "author", "citation_publisher"} and not self.publisher:
            self.publisher = content
        elif (
            name
            in {
                "citation_country",
                "country",
                "countries",
                "coverage",
                "dc.coverage",
                "dcterms.coverage",
                "dcterms.spatial",
                "geo.country",
            }
            or property_name
            in {
                "country",
                "countries",
                "coverage",
                "dc:coverage",
                "dc.coverage",
                "dcterms:coverage",
                "dcterms.coverage",
                "dcterms:spatial",
                "dcterms.spatial",
            }
            or itemprop in {"country", "spatialcoverage", "contentlocation"}
        ):
            self.geography.extend(_country_values(content))

    def _parse_json_ld(self, script_text: str) -> None:
        parsed = load_json_ld(script_text.strip(), self.limits)

        if isinstance(parsed, list):
            self.json_ld.extend(parsed)
        else:
            self.json_ld.append(parsed)


def _url_extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    match = re.search(r"(\.[a-z0-9]+)$", path)
    return match.group(1) if match else ""
