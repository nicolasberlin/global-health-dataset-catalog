"""Select one Dataset and resolve only bounded, local JSON-LD references."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from collector.budget import check_collection_budget
from collector.extraction.limits import (
    DEFAULT_EXTRACTION_LIMITS,
    ExtractionLimits,
    enforce_limit,
    json_objects,
)
from collector.storage.metadata import normalize_doi
from collector.url_utils import normalize_http_url


@dataclass(frozen=True)
class DatasetScope:
    nodes: tuple[dict[str, object], ...] = ()
    ambiguous: bool = False
    multiple: bool = False


def select_dataset_scope(
    evidence: object, page_url: str, canonical_url: str = "", *, citation_doi: str = "",
    expected_identity: dict[str, str] | None = None,
    limits: ExtractionLimits = DEFAULT_EXTRACTION_LIMITS,
) -> DatasetScope:
    objects = list(json_objects(evidence, limits))
    index: dict[str, dict[str, object]] = {}
    for node in objects:
        check_collection_budget()
        key = _reference_id(node.get("@id"), page_url)
        if key:
            index[key] = {**index.get(key, {}), **node}
    candidates: list[dict[str, object]] = []
    seen: set[str | int] = set()
    for node in objects:
        check_collection_budget()
        if not _is_type(node, "Dataset"):
            continue
        key = _reference_id(node.get("@id"), page_url)
        identity = key or id(node)
        if identity not in seen:
            seen.add(identity)
            candidates.append(index.get(key, node))
    if not candidates:
        return DatasetScope()
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        urls = {value for value in (normalize_http_url(page_url),
                                   normalize_http_url(canonical_url)) if value}
        identity = expected_identity or {}
        persistent_id = identity.get("persistent_id", "")
        dois = {value for value in (normalize_doi(citation_doi), normalize_doi(page_url),
                                   normalize_doi(canonical_url), normalize_doi(persistent_id))
                if value}
        main_entities = {
            _reference_id(value, page_url)
            for node in objects if _is_type(node, "WebPage") and _matches_url(node, urls, page_url)
            for value in _identifiers(node.get("mainEntity"))
        }
        main_entity_objects = {
            id(value)
            for node in objects if _is_type(node, "WebPage") and _matches_url(node, urls, page_url)
            for value in _embedded_objects(node.get("mainEntity"))
        }
        identity_resolver = _LocalResolver(index, page_url, limits)
        native_identifiers = {
            value for value in (identity.get("native_id"), persistent_id)
            if value and not normalize_doi(value)
        }
        scores = []
        for node in candidates:
            values = [value for key in ("@id", "url", "identifier")
                      for value in _identifiers(identity_resolver.resolve(node.get(key)))]
            scores.append(_identity_score(
                node, urls, dois, main_entities, page_url,
                native_identifiers, values, id(node) in main_entity_objects,
            ))
        highest = max(scores)
        if not highest or scores.count(highest) != 1:
            return DatasetScope(ambiguous=True, multiple=True)
        chosen = candidates[scores.index(highest)]
    resolver = _LocalResolver(index, page_url, limits)
    return DatasetScope(nodes=(resolver.resolve(chosen),), multiple=len(candidates) > 1)


def _is_type(node: dict, name: str) -> bool:
    values = node.get("@type", [])
    values = [values] if isinstance(values, str) else values
    return isinstance(values, list) and any(
        isinstance(value, str)
        and value.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1] == name
        for value in values
    )


def _identifiers(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _identifiers(item)]
    if isinstance(value, dict):
        return [text for key in ("@id", "url", "value")
                for text in _identifiers(value.get(key))]
    return []


def _embedded_objects(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _reference_id(value: object, page_url: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return value if value.startswith("_:") else urljoin(page_url, value.strip())
    except ValueError:
        return ""


def _matches_url(node: dict, urls: set[str], page_url: str) -> bool:
    return any(
        normalize_http_url(value, page_url) in urls
        for key in ("@id", "url", "mainEntityOfPage") for value in _identifiers(node.get(key))
    )


def _identity_score(
    node: dict, urls: set[str], dois: set[str], entities: set[str], base: str,
    identifiers: set[str], values: list[str], is_main_entity: bool,
):
    return (
        8 * any(normalize_doi(value) in dois for value in values)
        + 4 * bool(identifiers.intersection(values))
        + 2 * (is_main_entity or _reference_id(node.get("@id"), base) in entities)
        + int(_matches_url(node, urls, base))
    )


class _LocalResolver:
    def __init__(self, index, page_url: str, limits: ExtractionLimits):
        self.index, self.page_url, self.limits = index, page_url, limits
        self.count = self.characters = 0

    def resolve(self, value, depth: int = 0, active: frozenset[str] = frozenset()):
        check_collection_budget()
        self.count += 1
        enforce_limit(self.count, self.limits.max_json_ld_nodes,
                      "Resolved JSON-LD node limit exceeded.")
        enforce_limit(depth, self.limits.max_json_ld_depth,
                      "Resolved JSON-LD nesting limit exceeded.")
        if isinstance(value, str):
            self.characters += len(value)
            enforce_limit(self.characters, self.limits.max_json_ld_chars,
                          "Resolved JSON-LD size limit exceeded.")
        if isinstance(value, list):
            return [self.resolve(item, depth + 1, active) for item in value]
        if not isinstance(value, dict):
            return value
        key = _reference_id(value.get("@id"), self.page_url)
        if key in active:
            return {"@id": value["@id"]}
        if key:
            value = {**self.index.get(key, {}), **value}
            active = active | {key}
        # Context documents are retained as evidence, never fetched or expanded.
        return {key: self.resolve(item, depth + 1, active)
                for key, item in value.items() if key != "@context"}
