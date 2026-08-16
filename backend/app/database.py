from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult

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

COLLECTED_DATASETS_SCHEMA = """
CREATE TABLE collected_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL DEFAULT '',
    dataset_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT '',
    hosting_platform TEXT NOT NULL DEFAULT '',
    uploader TEXT NOT NULL DEFAULT '',
    discovery_method TEXT NOT NULL DEFAULT '',
    dataset_probability REAL NOT NULL,
    dataset_signals TEXT NOT NULL DEFAULT '{}',
    health_probability REAL NOT NULL,
    health_label TEXT NOT NULL,
    health_signals TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

COLLECTED_DISTRIBUTIONS_SCHEMA = """
CREATE TABLE collected_distributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    format TEXT NOT NULL,
    probability REAL NOT NULL,
    anchor TEXT NOT NULL DEFAULT '',
    extension TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    nearby_text TEXT NOT NULL DEFAULT '',
    same_domain INTEGER NOT NULL DEFAULT 0,
    dom_path TEXT NOT NULL DEFAULT '',
    signals TEXT NOT NULL DEFAULT '{}',
    validation_final_url TEXT NOT NULL DEFAULT '',
    validation_ok INTEGER NOT NULL DEFAULT 0,
    validation_http_status INTEGER,
    validation_mime_type TEXT NOT NULL DEFAULT '',
    validation_size_bytes INTEGER,
    validation_etag TEXT NOT NULL DEFAULT '',
    validation_last_modified TEXT NOT NULL DEFAULT '',
    validation_content_disposition TEXT NOT NULL DEFAULT '',
    validation_error TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(dataset_id) REFERENCES collected_datasets(id) ON DELETE CASCADE,
    UNIQUE(dataset_id, url, format)
)
"""


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        _ensure_data_sources_table(connection)
        _ensure_collected_tables(connection)
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


def save_collected_datasets(
    source_url: str,
    datasets: list[CollectedDataset],
) -> list[CollectedDataset]:
    saved_datasets: list[CollectedDataset] = []

    with get_connection() as connection:
        _ensure_collected_tables(connection)
        for dataset in datasets:
            row = _upsert_collected_dataset(connection, source_url, dataset)
            dataset_id = int(row["id"])
            connection.execute(
                "DELETE FROM collected_distributions WHERE dataset_id = ?",
                (dataset_id,),
            )
            validation_by_url = {
                validation.url: validation
                for validation in dataset.validation_results
            }
            for distribution in dataset.distributions:
                _insert_collected_distribution(
                    connection,
                    dataset_id,
                    distribution,
                    validation_by_url.get(distribution.url),
                )

            saved_datasets.append(
                CollectedDataset(
                    dataset_url=str(row["dataset_url"]),
                    title=str(row["title"]),
                    description=str(row["description"]),
                    publisher=str(row["publisher"]),
                    hosting_platform=str(row["hosting_platform"]),
                    uploader=str(row["uploader"]),
                    dataset_probability=float(row["dataset_probability"]),
                    dataset_signals=_deserialize_signals(str(row["dataset_signals"])),
                    health_probability=float(row["health_probability"]),
                    health_label=row["health_label"],
                    health_signals=_deserialize_signals(str(row["health_signals"])),
                    distributions=dataset.distributions,
                    discovery_method=str(row["discovery_method"]),
                    validation_results=dataset.validation_results,
                    source_url=str(row["source_url"]),
                    database_id=dataset_id,
                    updated_at=str(row["updated_at"]),
                )
            )

    return saved_datasets


def list_collected_datasets() -> list[CollectedDataset]:
    with get_connection() as connection:
        _ensure_collected_tables(connection)
        dataset_rows = connection.execute(
            """
            SELECT id, source_url, dataset_url, title, description, publisher,
                   hosting_platform, uploader, discovery_method,
                   dataset_probability, dataset_signals, health_probability,
                   health_label, health_signals, updated_at
            FROM collected_datasets
            ORDER BY updated_at DESC, title
            """
        ).fetchall()
        distribution_rows = connection.execute(
            """
            SELECT *
            FROM collected_distributions
            ORDER BY probability DESC, url
            """
        ).fetchall()

    distributions_by_dataset_id: dict[int, list[sqlite3.Row]] = {}
    for row in distribution_rows:
        distributions_by_dataset_id.setdefault(int(row["dataset_id"]), []).append(row)

    return [
        _collected_dataset_from_rows(
            dataset_row,
            distributions_by_dataset_id.get(int(dataset_row["id"]), []),
        )
        for dataset_row in dataset_rows
    ]


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


def _ensure_collected_tables(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "collected_datasets"):
        connection.execute(COLLECTED_DATASETS_SCHEMA)
    if not _table_exists(connection, "collected_distributions"):
        connection.execute(COLLECTED_DISTRIBUTIONS_SCHEMA)


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


def _upsert_collected_dataset(
    connection: sqlite3.Connection,
    source_url: str,
    dataset: CollectedDataset,
) -> sqlite3.Row:
    connection.execute(
        """
        INSERT INTO collected_datasets (
            source_url, dataset_url, title, description, publisher,
            hosting_platform, uploader, discovery_method, dataset_probability,
            dataset_signals, health_probability, health_label, health_signals
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_url) DO UPDATE SET
            source_url = excluded.source_url,
            title = excluded.title,
            description = excluded.description,
            publisher = excluded.publisher,
            hosting_platform = excluded.hosting_platform,
            uploader = excluded.uploader,
            discovery_method = excluded.discovery_method,
            dataset_probability = excluded.dataset_probability,
            dataset_signals = excluded.dataset_signals,
            health_probability = excluded.health_probability,
            health_label = excluded.health_label,
            health_signals = excluded.health_signals,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            source_url,
            dataset.dataset_url,
            dataset.title,
            dataset.description,
            dataset.publisher,
            dataset.hosting_platform,
            dataset.uploader,
            dataset.discovery_method,
            dataset.dataset_probability,
            _serialize_signals(dataset.dataset_signals),
            dataset.health_probability,
            dataset.health_label,
            _serialize_signals(dataset.health_signals),
        ),
    )
    return connection.execute(
        """
        SELECT id, source_url, dataset_url, title, description, publisher,
               hosting_platform, uploader, discovery_method, dataset_probability,
               dataset_signals, health_probability, health_label, health_signals,
               updated_at
        FROM collected_datasets
        WHERE dataset_url = ?
        """,
        (dataset.dataset_url,),
    ).fetchone()


def _insert_collected_distribution(
    connection: sqlite3.Connection,
    dataset_id: int,
    distribution: DistributionCandidate,
    validation: ValidationResult | None,
) -> None:
    connection.execute(
        """
        INSERT INTO collected_distributions (
            dataset_id, url, format, probability, anchor, extension, mime_type,
            nearby_text, same_domain, dom_path, signals, validation_final_url,
            validation_ok, validation_http_status, validation_mime_type,
            validation_size_bytes, validation_etag, validation_last_modified,
            validation_content_disposition, validation_error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            distribution.url,
            distribution.format,
            distribution.probability,
            distribution.anchor,
            distribution.extension,
            distribution.mime_type,
            distribution.nearby_text,
            int(distribution.same_domain),
            distribution.dom_path,
            _serialize_signals(distribution.signals),
            validation.final_url if validation else "",
            int(validation.ok) if validation else 0,
            validation.http_status if validation else None,
            validation.mime_type if validation else "",
            validation.size_bytes if validation else None,
            validation.etag if validation else "",
            validation.last_modified if validation else "",
            validation.content_disposition if validation else "",
            validation.error if validation else "",
        ),
    )


def _collected_dataset_from_rows(
    dataset_row: sqlite3.Row,
    distribution_rows: list[sqlite3.Row],
) -> CollectedDataset:
    distributions = [
        DistributionCandidate(
            url=str(row["url"]),
            format=str(row["format"]),
            probability=float(row["probability"]),
            anchor=str(row["anchor"]),
            extension=str(row["extension"]),
            mime_type=str(row["mime_type"]),
            nearby_text=str(row["nearby_text"]),
            same_domain=bool(row["same_domain"]),
            dom_path=str(row["dom_path"]),
            signals=_deserialize_signals(str(row["signals"])),
        )
        for row in distribution_rows
    ]
    validation_results = [
        ValidationResult(
            url=str(row["url"]),
            final_url=str(row["validation_final_url"]),
            format=str(row["format"]),
            ok=bool(row["validation_ok"]),
            http_status=row["validation_http_status"],
            mime_type=str(row["validation_mime_type"]),
            size_bytes=row["validation_size_bytes"],
            etag=str(row["validation_etag"]),
            last_modified=str(row["validation_last_modified"]),
            content_disposition=str(row["validation_content_disposition"]),
            error=str(row["validation_error"]),
        )
        for row in distribution_rows
    ]

    return CollectedDataset(
        dataset_url=str(dataset_row["dataset_url"]),
        title=str(dataset_row["title"]),
        description=str(dataset_row["description"]),
        publisher=str(dataset_row["publisher"]),
        hosting_platform=str(dataset_row["hosting_platform"]),
        uploader=str(dataset_row["uploader"]),
        dataset_probability=float(dataset_row["dataset_probability"]),
        dataset_signals=_deserialize_signals(str(dataset_row["dataset_signals"])),
        health_probability=float(dataset_row["health_probability"]),
        health_label=dataset_row["health_label"],
        health_signals=_deserialize_signals(str(dataset_row["health_signals"])),
        distributions=distributions,
        discovery_method=str(dataset_row["discovery_method"]),
        validation_results=validation_results,
        source_url=str(dataset_row["source_url"]),
        database_id=int(dataset_row["id"]),
        updated_at=str(dataset_row["updated_at"]),
    )


def _serialize_signals(signals: dict[str, object]) -> str:
    return json.dumps(signals, sort_keys=True, default=str)


def _deserialize_signals(value: str) -> dict[str, object]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}
