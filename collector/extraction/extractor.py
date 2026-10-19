from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from collector.budget import check_collection_budget
from collector.extraction.errors import ExtractionError
from collector.extraction.graph import select_dataset_scope
from collector.extraction.limits import (
    DEFAULT_EXTRACTION_LIMITS,
    ExtractionLimits,
    enforce_limit,
    json_objects,
    load_json_ld,
)
from collector.source_identity import identify_source
from collector.storage.metadata import normalize_doi
from collector.storage.models import LinkCandidate, PageSnapshot
from collector.url_utils import canonicalize_url, same_domain, select_dataset_url

SKIP_TEXT_TAGS = {"script", "style", "noscript", "svg"}
BLOCKED_LINK_SCHEMES = {"mailto", "tel", "javascript"}
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


def extract_page(
    url: str, html: str, *, limits: ExtractionLimits = DEFAULT_EXTRACTION_LIMITS,
    expected_identity: dict[str, str] | None = None,
) -> PageSnapshot:
    parser = _PageHTMLParser(url, limits)
    _feed_html(parser, html)
    if parser._active_json_ld_parts is not None:
        raise ExtractionError("JSON-LD script was not closed.")
    canonical_url = select_dataset_url(url, parser.canonical_href)
    scope = select_dataset_scope(
        parser.json_ld, url, canonical_url, citation_doi=parser.doi,
        expected_identity=expected_identity, limits=limits,
    )
    scoped_json = list(scope.nodes)
    source_identity = identify_source(canonical_url)
    publisher = (
        _publisher_from_json_ld(scoped_json)
        or (parser.publisher or source_identity.publisher if not scope.nodes else "")
    )
    geography = _dedupe(
        [
            *(parser.geography if not scope.nodes else []),
            *_geography_from_json_ld(scoped_json),
        ]
    )

    title = _normalize_text(" ".join(parser.title_parts))
    h1 = _normalize_text(" ".join(parser.h1_parts))
    description = parser.meta_description or parser.og_description
    text = _normalize_text(" ".join(parser.text_parts))
    if scope.multiple and scope.nodes:
        selected = scope.nodes[0]
        title = _metadata_text(selected.get("name"))
        h1 = ""
        description = _metadata_text(selected.get("description"))
        text = _normalize_text(" ".join((title, description)))
    if scope.ambiguous:
        title = h1 = description = publisher = text = ""
        geography = []
    return PageSnapshot(
        url=url,
        canonical_url=canonical_url,
        title=title,
        h1=h1,
        meta_description=description if not scope.ambiguous else "",
        og_title=parser.og_title if not scope.multiple else "",
        og_description=parser.og_description if not scope.multiple else "",
        headings=tuple(dict.fromkeys(parser.heading_parts)) if not scope.multiple else (),
        text=text,
        publisher=publisher,
        hosting_platform=source_identity.hosting_platform,
        uploader=source_identity.uploader,
        geography=tuple(geography),
        date_of_publication=_date_from_json_ld(scoped_json),
        doi=(_doi_from_json_ld(scoped_json) or parser.doi) if not scope.ambiguous else "",
        dataset_url=canonical_url,
        diseases=tuple(_diseases_from_text(" ".join([title, h1, description, text])))
        if not scope.ambiguous else (),
        size_of_dataset=_size_from_json_ld(scoped_json),
        demographic_information=tuple(
            _demographics_from_text(" ".join([title, h1, description, text]))
        ) if not scope.ambiguous else (),
        sharing_license=_license_from_json_ld(scoped_json),
        modality_of_data=tuple(_modalities_from_json_ld(scoped_json)),
        description_of_dataset=description,
        links=tuple(parser.links) if not scope.multiple else (),
        json_ld=tuple(parser.json_ld),
        dataset_json_ld=scope.nodes,
        dataset_metadata_ambiguous=scope.ambiguous,
    )


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


def _iter_json_objects(value: object) -> list[dict[str, object]]:
    return list(json_objects(value))


def _root_objects(value: list[object]):
    return (item for item in value if isinstance(item, dict))


def _metadata_text(value: object) -> str:
    return html_to_text(value) if isinstance(value, str) else ""


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


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


def _url_extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    match = re.search(r"(\.[a-z0-9]+)$", path)
    return match.group(1) if match else ""


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
