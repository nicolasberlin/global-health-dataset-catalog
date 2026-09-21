"""Metadata evidence retained after classification and resource validation."""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import unquote

from collector.extraction.dataset_metadata import MISSING_DATASET_METADATA_VALUE
from collector.storage.models import CollectedDataset, PageSnapshot

METADATA_FIELDS = ("date_of_publication", "sharing_license", "doi")


def normalize_doi(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = unquote(value.strip())
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else ""


def metadata_evidence(
    dataset: PageSnapshot | CollectedDataset, *, kind: str, source_url: str,
) -> dict[str, object]:
    return {
        field: [{"value": getattr(dataset, field), "kind": kind, "source_url": source_url}]
        for field in METADATA_FIELDS if getattr(dataset, field)
    }


def enrich_from_repository(
    dataset: CollectedDataset, candidate: dict[str, object],
) -> CollectedDataset:
    """Fill missing values only, preserving conflicting provider evidence.

    Call only after collection validation and after establishing that this
    candidate is the input of the individual-dataset collection job.
    """
    metadata = candidate.get("metadata") or {}
    values = {
        "date_of_publication": str(candidate.get("publication_date") or ""),
        "sharing_license": str(metadata.get("Sharing license") or ""),
        "doi": normalize_doi(candidate.get("doi")),
    }
    values = {field: value.strip() if value.strip() != MISSING_DATASET_METADATA_VALUE else ""
              for field, value in values.items()}
    evidence = {key: list(value) for key, value in dataset.metadata_provenance.items()}
    for field, value in values.items():
        if not value:
            continue
        entry = {
            "value": value, "kind": "repository",
            "source_url": str(candidate["url"]),
            "provider": str(candidate.get("provider") or ""),
        }
        entries = evidence.setdefault(field, [])
        if entry not in entries:
            entries.append(entry)
    return replace(
        dataset, metadata_provenance=evidence,
        **{field: getattr(dataset, field) or value for field, value in values.items()},
    )
