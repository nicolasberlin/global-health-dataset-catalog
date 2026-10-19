"""Internal resource bounds for HTML and local JSON-LD evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass

from collector.budget import check_collection_budget
from collector.extraction.errors import ExtractionError


@dataclass(frozen=True)
class ExtractionLimits:
    max_html_chars: int = 1_000_000
    max_html_depth: int = 128
    max_html_nodes: int = 20_000
    max_links: int = 2_000
    max_evidence_chars: int = 1_000_000
    max_dom_path_chars: int = 1_024
    max_attribute_chars: int = 16_384
    max_json_ld_chars: int = 262_144
    max_json_ld_nodes: int = 20_000
    max_json_ld_depth: int = 64
    max_json_ld_scripts: int = 32

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("Extraction limits must be positive integers.")


DEFAULT_EXTRACTION_LIMITS = ExtractionLimits()


def enforce_limit(value: int, maximum: int, reason: str) -> None:
    if value > maximum:
        raise ExtractionError(reason, code="extraction_limit_exceeded")


def json_objects(value: object, limits: ExtractionLimits = DEFAULT_EXTRACTION_LIMITS):
    """Iterate local evidence without recursive traversal or remote contexts."""
    pending = [(value, 0)]
    count = 0
    while pending:
        check_collection_budget()
        item, depth = pending.pop()
        count += 1
        enforce_limit(count, limits.max_json_ld_nodes, "JSON-LD node limit exceeded.")
        enforce_limit(depth, limits.max_json_ld_depth, "JSON-LD nesting limit exceeded.")
        if isinstance(item, dict):
            yield item
            children = list(item.values())
        elif isinstance(item, (list, tuple)):
            children = item
        else:
            continue
        enforce_limit(count + len(pending) + len(children), limits.max_json_ld_nodes,
                      "JSON-LD node limit exceeded.")
        pending.extend((child, depth + 1) for child in reversed(children))


def load_json_ld(text: str, limits: ExtractionLimits):
    enforce_limit(len(text), limits.max_json_ld_chars, "JSON-LD size limit exceeded.")
    depth, quoted, escaped = 0, False, False
    for index, character in enumerate(text):
        if index % 1_024 == 0:
            check_collection_budget()
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            enforce_limit(depth, limits.max_json_ld_depth, "JSON-LD nesting limit exceeded.")
        elif character in "]}":
            depth -= 1
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise ExtractionError("JSON-LD content could not be parsed.") from error
    # Validate the complete tree, including lists and scalars, before retaining it.
    for _ in json_objects(value, limits):
        pass
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON values are not allowed.")
