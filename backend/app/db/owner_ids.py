"""Validate persisted owner identifiers shared by all database domains."""

from __future__ import annotations


def validate_owner_id(owner_id: str) -> str:
    """Validate the stored owner ID without silently trimming or changing it."""
    normalized_owner_id = owner_id.strip()
    if not normalized_owner_id:
        raise ValueError("Search owner ID is required.")
    if normalized_owner_id != owner_id or len(normalized_owner_id) > 200:
        raise ValueError("Search owner ID must be trimmed and at most 200 characters.")
    return normalized_owner_id
