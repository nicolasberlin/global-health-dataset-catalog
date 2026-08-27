from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from collector.source_identity import identify_source
from collector.storage.models import LinkCandidate, PageSnapshot
from collector.url_utils import canonicalize_url, same_domain

SKIP_TEXT_TAGS = {"script", "style", "noscript", "svg"}
BLOCKED_LINK_SCHEMES = {"mailto", "tel", "javascript"}


class _PageHTMLParser(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = url
        self.stack: list[str] = []
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[LinkCandidate] = []
        self.json_ld: list[object] = []
        self.canonical_url = ""
        self.meta_description = ""
        self.og_title = ""
        self.og_description = ""
        self.publisher = ""
        self.geography: list[str] = []
        self._active_link: dict[str, object] | None = None
        self._active_json_ld_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.stack.append(tag)
        attributes = {name.lower(): value or "" for name, value in attrs}

        if tag == "link":
            rel = attributes.get("rel", "").lower()
            href = attributes.get("href", "")
            if "canonical" in rel and href:
                self.canonical_url = canonicalize_url(href, self.url)

        if tag == "meta":
            self._handle_meta(attributes)

        if tag == "a" and attributes.get("href"):
            href = attributes["href"].strip()
            scheme = urlsplit(href).scheme.lower()
            if scheme not in BLOCKED_LINK_SCHEMES:
                resolved_url = canonicalize_url(href, self.url)
                self._active_link = {
                    "url": resolved_url,
                    "anchor_parts": [],
                    "dom_path": "/".join(self.stack),
                }

        if tag == "script" and "ld+json" in attributes.get("type", "").lower():
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

        if tag in self.stack:
            last_index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[last_index:]

    def handle_data(self, data: str) -> None:
        if self._active_json_ld_parts is not None:
            self._active_json_ld_parts.append(data)
            return

        text = _normalize_text(data)
        if not text:
            return

        if self._active_link is not None:
            self._active_link["anchor_parts"].append(text)

        if "title" in self.stack:
            self.title_parts.append(text)

        if "h1" in self.stack:
            self.h1_parts.append(text)

        if self.stack and self.stack[-1] in {"h2", "h3"}:
            self.heading_parts.append(text)

        if not any(tag in SKIP_TEXT_TAGS for tag in self.stack):
            self.text_parts.append(text)

    def _handle_meta(self, attributes: dict[str, str]) -> None:
        name = attributes.get("name", "").lower()
        property_name = attributes.get("property", "").lower()
        itemprop = attributes.get("itemprop", "").lower()
        content = html_to_text(attributes.get("content", ""))

        if not content:
            return

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
        try:
            parsed = json.loads(script_text.strip())
        except json.JSONDecodeError:
            return

        if isinstance(parsed, list):
            self.json_ld.extend(parsed)
        else:
            self.json_ld.append(parsed)


def extract_page(url: str, html: str) -> PageSnapshot:
    parser = _PageHTMLParser(url)
    parser.feed(html)
    canonical_url = parser.canonical_url or canonicalize_url(url)
    source_identity = identify_source(canonical_url)
    publisher = (
        parser.publisher
        or _publisher_from_json_ld(parser.json_ld)
        or source_identity.publisher
    )
    geography = _dedupe(
        [
            *parser.geography,
            *_geography_from_json_ld(parser.json_ld),
        ]
    )

    title = _normalize_text(" ".join(parser.title_parts))
    h1 = _normalize_text(" ".join(parser.h1_parts))
    description = parser.meta_description or parser.og_description
    text = _normalize_text(" ".join(parser.text_parts))
    return PageSnapshot(
        url=url,
        canonical_url=canonical_url,
        title=title,
        h1=h1,
        meta_description=parser.meta_description,
        og_title=parser.og_title,
        og_description=parser.og_description,
        headings=tuple(dict.fromkeys(parser.heading_parts)),
        text=text,
        publisher=publisher,
        hosting_platform=source_identity.hosting_platform,
        uploader=source_identity.uploader,
        geography=tuple(geography),
        date_of_publication=_date_from_json_ld(parser.json_ld),
        dataset_url=canonical_url,
        diseases=tuple(_diseases_from_text(" ".join([title, h1, description, text]))),
        size_of_dataset=_size_from_json_ld(parser.json_ld),
        demographic_information=tuple(
            _demographics_from_text(" ".join([title, h1, description, text]))
        ),
        sharing_license=_license_from_json_ld(parser.json_ld),
        modality_of_data=tuple(_modalities_from_json_ld(parser.json_ld)),
        description_of_dataset=description,
        links=tuple(parser.links),
        json_ld=tuple(parser.json_ld),
    )


def _publisher_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _iter_json_objects(json_ld_items):
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
    for item in _iter_json_objects(json_ld_items):
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
    for item in _iter_json_objects(json_ld_items):
        for key in ("datePublished", "publicationDate", "dct:issued", "issued"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)

    return ""


def _license_from_json_ld(json_ld_items: list[object]) -> str:
    for item in _iter_json_objects(json_ld_items):
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
    for item in _iter_json_objects(json_ld_items):
        for key in ("size", "contentSize", "content_size"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)

    return ""


def _modalities_from_json_ld(json_ld_items: list[object]) -> list[str]:
    values: list[str] = []
    for item in _iter_json_objects(json_ld_items):
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
    objects: list[dict[str, object]] = []

    if isinstance(value, dict):
        objects.append(value)
        for nested in value.values():
            objects.extend(_iter_json_objects(nested))
    elif isinstance(value, list):
        for item in value:
            objects.extend(_iter_json_objects(item))

    return objects


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def html_to_text(value: str) -> str:
    if "<" not in value and "&" not in value:
        return _normalize_text(value)

    parser = _TextHTMLParser()
    parser.feed(unescape(value))
    return _normalize_text(" ".join(parser.text_parts))


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.stack:
            last_index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[last_index:]

    def handle_data(self, data: str) -> None:
        if any(tag in SKIP_TEXT_TAGS for tag in self.stack):
            return

        text = _normalize_text(data)
        if text:
            self.text_parts.append(text)


def _url_extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    match = re.search(r"(\.[a-z0-9]+)$", path)
    return match.group(1) if match else ""
