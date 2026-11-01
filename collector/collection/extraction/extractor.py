"""Assemble a page snapshot from bounded HTML and selected dataset evidence."""

from __future__ import annotations

from collector.collection.extraction.graph import select_dataset_scope
from collector.collection.extraction.html import _PageHTMLParser
from collector.collection.extraction.json_ld import (
    _date_from_json_ld,
    _doi_from_json_ld,
    _geography_from_json_ld,
    _license_from_json_ld,
    _modalities_from_json_ld,
    _publisher_from_json_ld,
    _size_from_json_ld,
)
from collector.collection.extraction.source_identity import identify_source
from collector.metadata.dataset import (
    _dedupe,
    _demographics_from_text,
    _diseases_from_text,
    _metadata_text,
)
from collector.models import PageSnapshot
from collector.parsing.errors import ExtractionError
from collector.parsing.html_text import _feed_html, _normalize_text
from collector.parsing.html_text import html_to_text as html_to_text
from collector.parsing.limits import DEFAULT_EXTRACTION_LIMITS, ExtractionLimits
from collector.url_utils import select_dataset_url


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
