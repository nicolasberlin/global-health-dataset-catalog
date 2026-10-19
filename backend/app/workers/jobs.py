"""Persisted worker inputs; dictionaries remain compatible with existing stores."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID


class SearchJob(TypedDict):
    id: UUID
    owner_id: str
    query: str
    client_key: str | None
    attempt_token: UUID
    attempt_number: int


class ClassificationJob(TypedDict):
    id: UUID
    owner_id: str
    updated_at: str
    title: str
    description: str
    url: str
    source: str
    search_query: str
    publisher: str
    publication_date: str
    doi: str
    keywords: list[str]
    metadata: dict[str, Any]


class CollectionJob(TypedDict):
    id: int
    updated_at: str
    source_url: str
    kind: str
    collection_deadline_at: str | datetime | None
