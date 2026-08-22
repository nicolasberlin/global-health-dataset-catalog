from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

from collector.storage.models import DistributionCandidate, LinkCandidate, PageSnapshot
from collector.url_utils import canonicalize_url

FORMAT_BY_EXTENSION = {
    ".csv": "CSV",
    ".tsv": "TSV",
    ".xls": "XLS",
    ".xlsx": "XLSX",
    ".json": "JSON",
    ".jsonl": "JSONL",
    ".xml": "XML",
    ".parquet": "PARQUET",
    ".zip": "ZIP",
    ".gz": "GZ",
    ".sav": "SAV",
    ".dta": "DTA",
    ".sas7bdat": "SAS7BDAT",
    ".geojson": "GEOJSON",
}

MIME_BY_FORMAT = {
    "CSV": "text/csv",
    "TSV": "text/tab-separated-values",
    "XLS": "application/vnd.ms-excel",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "JSON": "application/json",
    "JSONL": "application/x-ndjson",
    "XML": "application/xml",
    "PARQUET": "application/vnd.apache.parquet",
    "ZIP": "application/zip",
    "GZ": "application/gzip",
    "GEOJSON": "application/geo+json",
}

DOWNLOAD_TERMS = {
    "api",
    "data",
    "dataset",
    "download",
    "export",
    "file",
    "resource",
    "resources",
    "telecharger",
}

EXCLUDED_EXTENSIONS = {".pdf", ".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".svg"}


def extract_distributions(page: PageSnapshot) -> list[DistributionCandidate]:
    candidates: list[DistributionCandidate] = []
    candidates.extend(_schema_distribution_candidates(page))

    for link in page.links:
        candidate = _candidate_from_link(link)
        if candidate is not None:
            candidates.append(candidate)

    return _deduplicate_candidates(candidates)


def guess_format(url: str, anchor: str = "", mime_type: str = "") -> tuple[str, str]:
    path_extension = _guess_path_extension(url)
    if path_extension in FORMAT_BY_EXTENSION:
        return FORMAT_BY_EXTENSION[path_extension], path_extension

    for extension, format_name in FORMAT_BY_EXTENSION.items():
        token = extension.removeprefix(".")
        if re.search(rf"\b{re.escape(token)}\b", mime_type.lower()):
            return format_name, extension

    if _looks_like_api(url, anchor):
        return "API", ""

    query_extension = _guess_query_extension(url)
    if query_extension in FORMAT_BY_EXTENSION:
        return FORMAT_BY_EXTENSION[query_extension], query_extension

    return "UNKNOWN", path_extension or query_extension


def _candidate_from_link(link: LinkCandidate) -> DistributionCandidate | None:
    format_name, extension = guess_format(link.url, link.anchor)
    if extension in EXCLUDED_EXTENSIONS:
        return None

    score = 0.0
    signals: dict[str, object] = {}
    combined = f"{link.url} {link.anchor} {link.nearby_text}".lower()

    if format_name != "UNKNOWN":
        score += 0.55
        signals["known_format"] = format_name

    if _looks_like_api(link.url, link.anchor):
        score += 0.35
        signals["api_pattern"] = True

    matched_terms = sorted(term for term in DOWNLOAD_TERMS if term in combined)
    if matched_terms:
        score += min(0.3, len(matched_terms) * 0.1)
        signals["download_terms"] = matched_terms

    if link.same_domain:
        score += 0.05
        signals["same_domain"] = True

    if score < 0.35:
        return None

    return DistributionCandidate(
        url=link.url,
        format=format_name,
        probability=min(score, 1.0),
        anchor=link.anchor,
        extension=extension,
        mime_type=MIME_BY_FORMAT.get(format_name, ""),
        nearby_text=link.nearby_text,
        same_domain=link.same_domain,
        dom_path=link.dom_path,
        signals=signals,
    )


def _schema_distribution_candidates(page: PageSnapshot) -> list[DistributionCandidate]:
    candidates: list[DistributionCandidate] = []

    for node in _iter_json_objects(page.json_ld):
        distribution = node.get("distribution")
        if distribution is None:
            continue

        distributions = distribution if isinstance(distribution, list) else [distribution]
        for item in distributions:
            if not isinstance(item, dict):
                continue

            url_value = (
                item.get("contentUrl")
                or item.get("downloadUrl")
                or item.get("downloadURL")
                or item.get("url")
            )
            if not isinstance(url_value, str) or not url_value.strip():
                continue

            encoding_format = str(item.get("encodingFormat") or item.get("contentType") or "")
            url = canonicalize_url(url_value, page.canonical_url)
            format_name, extension = guess_format(url, mime_type=encoding_format)
            candidates.append(
                DistributionCandidate(
                    url=url,
                    format=format_name,
                    probability=0.95,
                    extension=extension,
                    mime_type=encoding_format or MIME_BY_FORMAT.get(format_name, ""),
                    same_domain=True,
                    signals={"schema_distribution": True},
                )
            )

    return candidates


def _deduplicate_candidates(
    candidates: list[DistributionCandidate],
) -> list[DistributionCandidate]:
    best_by_key: dict[tuple[str, str], DistributionCandidate] = {}

    for candidate in candidates:
        key = (canonicalize_url(candidate.url), candidate.format)
        current = best_by_key.get(key)
        if current is None or candidate.probability > current.probability:
            best_by_key[key] = candidate

    return sorted(best_by_key.values(), key=lambda item: item.probability, reverse=True)


def _guess_path_extension(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.lower()
    for extension in sorted(
        [*FORMAT_BY_EXTENSION.keys(), *EXCLUDED_EXTENSIONS],
        key=len,
        reverse=True,
    ):
        if path.endswith(extension):
            return extension

    return ""


def _guess_query_extension(url: str) -> str:
    parts = urlsplit(url)
    query_text = " ".join(value.lower() for _, value in parse_qsl(parts.query))
    for extension in sorted(FORMAT_BY_EXTENSION.keys(), key=len, reverse=True):
        if query_text.endswith(extension) or extension.removeprefix(".") in query_text.split():
            return extension

    return ""


def _looks_like_api(url: str, anchor: str = "") -> bool:
    combined = f"{url} {anchor}".lower()
    return any(marker in combined for marker in ("/api/", "api/", "format=json", "export?"))


def _iter_json_objects(value: object) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []

    if isinstance(value, dict):
        objects.append(value)
        for nested in value.values():
            objects.extend(_iter_json_objects(nested))
    elif isinstance(value, (list, tuple)):
        for item in value:
            objects.extend(_iter_json_objects(item))

    return objects
