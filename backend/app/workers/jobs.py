"""Required claim fields, rather than complete SQL rows, used by each worker."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, NotRequired, TypedDict
from uuid import UUID


class SearchJob(TypedDict):
    """A fenced discovery attempt; origin is available on persisted recovery rows."""

    id: UUID
    owner_id: str
    query: str
    client_key: str | None
    attempt_token: UUID
    attempt_number: int
    origin: NotRequired[Literal["database", "online"]]


class ClassificationJob(TypedDict):
    """Candidate metadata and the claim version used to guard its writes."""

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
    """Authoritative source, claim version and optional collection deadline."""

    id: int
    updated_at: str
    source_url: str
    kind: Literal["source", "repository_candidate"]
    collection_deadline_at: str | datetime | None
