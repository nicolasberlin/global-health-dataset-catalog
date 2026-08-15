from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DATABASE_PATH = Path(
    os.environ.get(
        "GLOBAL_HEALTH_DB_PATH",
        Path(__file__).resolve().parents[1] / "global_health.db",
    )
)

DATA_SOURCE_SEEDS = [
    {
        "source_key": "who_gho_indicators",
        "name": "WHO Global Health Observatory - Indicators",
        "description": "Official WHO catalogue of global health indicators.",
        "theme": "General",
        "page_url": "https://www.who.int/data/gho/data/indicators/",
    },
    {
        "source_key": "who_gho_life_expectancy",
        "name": "WHO Global Health Observatory - Life expectancy",
        "description": "Official WHO dataset page for life expectancy at birth.",
        "theme": "Mortality",
        "page_url": "https://www.who.int/data/gho/data/indicators/indicator-details/GHO/life-expectancy-at-birth-%28years%29",
    },
]

DATA_SOURCES_SCHEMA = """
CREATE TABLE data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    theme TEXT NOT NULL DEFAULT 'General',
    page_url TEXT NOT NULL
)
"""


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        _ensure_data_sources_table(connection)
        _seed_data_sources(connection)
        connection.execute("DROP TABLE IF EXISTS accounts")


def list_data_sources() -> list[dict[str, int | str]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, source_key, name, description, theme, page_url
            FROM data_sources
            ORDER BY theme, name
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_data_source(source_id: int) -> dict[str, int | str] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, source_key, name, description, theme, page_url
            FROM data_sources
            WHERE id = ?
            """,
            (source_id,),
        ).fetchone()

    return dict(row) if row else None


def upsert_data_source(
    source_key: str,
    name: str,
    description: str,
    theme: str,
    page_url: str,
) -> dict[str, int | str]:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO data_sources (source_key, name, description, theme, page_url)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                theme = excluded.theme,
                page_url = excluded.page_url
            """,
            (source_key, name, description, theme, page_url),
        )
        row = connection.execute(
            """
            SELECT id, source_key, name, description, theme, page_url
            FROM data_sources
            WHERE source_key = ?
            """,
            (source_key,),
        ).fetchone()

    return dict(row)


def _ensure_data_sources_table(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "data_sources"):
        connection.execute(DATA_SOURCES_SCHEMA)
        return

    columns = _table_columns(connection, "data_sources")
    expected_columns = {"id", "source_key", "name", "description", "theme", "page_url"}

    if columns == expected_columns:
        return

    connection.execute("ALTER TABLE data_sources RENAME TO data_sources_old")
    connection.execute(DATA_SOURCES_SCHEMA)

    old_columns = _table_columns(connection, "data_sources_old")
    required_old_columns = {"id", "name", "description", "page_url"}
    if required_old_columns.issubset(old_columns):
        source_key_expression = (
            "source_key"
            if "source_key" in old_columns
            else "'legacy_' || lower(replace(name, ' ', '_'))"
        )
        theme_expression = "theme" if "theme" in old_columns else "'General'"
        connection.execute(
            f"""
            INSERT INTO data_sources (id, source_key, name, description, theme, page_url)
            SELECT id, {source_key_expression}, name, description, {theme_expression}, page_url
            FROM data_sources_old
            WHERE page_url != ''
            """
        )

    connection.execute("DROP TABLE data_sources_old")


def _seed_data_sources(connection: sqlite3.Connection) -> None:
    for source in DATA_SOURCE_SEEDS:
        connection.execute(
            """
            INSERT INTO data_sources (source_key, name, description, theme, page_url)
            VALUES (:source_key, :name, :description, :theme, :page_url)
            ON CONFLICT(source_key) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                theme = excluded.theme,
                page_url = excluded.page_url
            """,
            source,
        )
        connection.execute(
            """
            DELETE FROM data_sources
            WHERE name = ? AND source_key != ?
            """,
            (source["name"], source["source_key"]),
        )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}
