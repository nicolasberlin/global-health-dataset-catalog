from __future__ import annotations

import re
from urllib.parse import urlsplit

from psycopg import errors

from . import db_schema
from .db_connection import _fetchall, _fetchone, _require_database_pool
from .db_schema import _require_current_schema

DATA_SOURCE_KEY_PATTERN_TEXT = db_schema.DATA_SOURCE_KEY_PATTERN_TEXT
DATA_SOURCE_KEY_PATTERN = re.compile(DATA_SOURCE_KEY_PATTERN_TEXT)


class ReservedDataSourceKeyError(ValueError):
    pass


class DuplicateDataSourceKeyError(ValueError):
    pass


class InvalidDataSourceKeyError(ValueError):
    pass


class InvalidDataSourceURLError(ValueError):
    pass


def reserved_data_source_keys() -> frozenset[str]:
    return frozenset(source["source_key"] for source in db_schema.DATA_SOURCE_SEEDS)


def normalize_data_source_key(source_key: str) -> str:
    normalized_key = source_key.strip()
    if not DATA_SOURCE_KEY_PATTERN.fullmatch(normalized_key):
        raise InvalidDataSourceKeyError(
            "Data source key must start with a lowercase letter or digit and "
            "contain only lowercase letters, digits, underscores, or hyphens."
        )
    return normalized_key


def _normalize_required_data_source_text(field_name: str, value: str) -> str:
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"Data source {field_name} must not be empty.")
    return normalized_value


def normalize_data_source_page_url(page_url: str) -> str:
    normalized_url = page_url.strip()
    try:
        parsed_url = urlsplit(normalized_url)
        port = parsed_url.port
    except ValueError as exception:
        raise InvalidDataSourceURLError(
            "Data source page URL must be a valid HTTP or HTTPS URL."
        ) from exception

    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or not parsed_url.hostname
        or (port is not None and not 0 <= port <= 65535)
        or any(character.isspace() for character in normalized_url)
    ):
        raise InvalidDataSourceURLError(
            "Data source page URL must be a valid HTTP or HTTPS URL."
        )
    return normalized_url


def _normalize_data_source_values(
    source_key: str,
    name: str,
    description: str,
    theme: str,
    page_url: str,
) -> tuple[str, str, str, str, str]:
    return (
        normalize_data_source_key(source_key),
        _normalize_required_data_source_text("name", name),
        description.strip(),
        _normalize_required_data_source_text("theme", theme),
        normalize_data_source_page_url(page_url),
    )


async def list_data_sources() -> list[dict[str, int | str]]:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _fetchall(
            connection,
            """
            SELECT id, source_key, name, description, theme, page_url
            FROM data_sources
            ORDER BY theme, name
            """,
        )

    return [dict(row) for row in rows]


async def get_data_source(source_id: int) -> dict[str, int | str] | None:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            SELECT id, source_key, name, description, theme, page_url
            FROM data_sources
            WHERE id = %s
            """,
            (source_id,),
        )

    return dict(row) if row else None


async def create_data_source(
    source_key: str,
    name: str,
    description: str,
    theme: str,
    page_url: str,
) -> dict[str, int | str]:
    source_key, name, description, theme, page_url = _normalize_data_source_values(
        source_key,
        name,
        description,
        theme,
        page_url,
    )
    if source_key in reserved_data_source_keys():
        raise ReservedDataSourceKeyError(
            f"Data source key {source_key!r} is reserved by the application."
        )

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        try:
            row = await _fetchone(
                connection,
                """
                INSERT INTO data_sources (
                    source_key, name, description, theme, page_url
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, source_key, name, description, theme, page_url
                """,
                (source_key, name, description, theme, page_url),
            )
        except errors.UniqueViolation as exception:
            raise DuplicateDataSourceKeyError(
                f"Data source key {source_key!r} already exists."
            ) from exception

    if row is None:
        raise RuntimeError("Data source creation did not return a row.")
    return dict(row)


async def upsert_collector_data_source(
    source_key: str,
    name: str,
    description: str,
    theme: str,
    page_url: str,
) -> dict[str, int | str]:
    """Create or update a data source discovered by the collector."""
    source_key, name, description, theme, page_url = _normalize_data_source_values(
        source_key,
        name,
        description,
        theme,
        page_url,
    )
    if source_key in reserved_data_source_keys():
        raise ReservedDataSourceKeyError(
            f"Data source key {source_key!r} is reserved by the application."
        )

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        row = await _fetchone(
            connection,
            """
            INSERT INTO data_sources (source_key, name, description, theme, page_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(source_key) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                theme = excluded.theme,
                page_url = excluded.page_url
            RETURNING id, source_key, name, description, theme, page_url
            """,
            (source_key, name, description, theme, page_url),
        )

    if row is None:
        raise RuntimeError("Data source upsert did not return a row.")
    return dict(row)


upsert_data_source = upsert_collector_data_source
