from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    DistributionCandidate,
    ValidationResult,
)

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1

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
RESERVED_DATA_SOURCE_KEYS = frozenset(
    source["source_key"] for source in DATA_SOURCE_SEEDS
)


class ReservedDataSourceKeyError(ValueError):
    pass


DATA_SOURCES_SCHEMA = """
CREATE TABLE data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE CHECK(source_key != ''),
    name TEXT NOT NULL CHECK(name != ''),
    description TEXT NOT NULL DEFAULT '',
    theme TEXT NOT NULL DEFAULT 'General' CHECK(theme != ''),
    page_url TEXT NOT NULL CHECK(page_url != '')
)
"""

HEALTH_LABELS = ("HEALTH", "PARTIALLY_HEALTH", "NON_HEALTH")

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
    dataset_probability REAL NOT NULL CHECK(dataset_probability >= 0 AND dataset_probability <= 1),
    dataset_signals TEXT NOT NULL DEFAULT '{}',
    health_probability REAL NOT NULL CHECK(health_probability >= 0 AND health_probability <= 1),
    health_label TEXT NOT NULL CHECK(health_label IN ('HEALTH', 'PARTIALLY_HEALTH', 'NON_HEALTH')),
    health_signals TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
    probability REAL NOT NULL CHECK(probability >= 0 AND probability <= 1),
    anchor TEXT NOT NULL DEFAULT '',
    extension TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    nearby_text TEXT NOT NULL DEFAULT '',
    same_domain INTEGER NOT NULL DEFAULT 0 CHECK(same_domain IN (0, 1)),
    dom_path TEXT NOT NULL DEFAULT '',
    signals TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TEXT NOT NULL DEFAULT '',
    validation_attempted INTEGER NOT NULL DEFAULT 0 CHECK(validation_attempted IN (0, 1)),
    validation_final_url TEXT NOT NULL DEFAULT '',
    validation_ok INTEGER NOT NULL DEFAULT 0 CHECK(validation_ok IN (0, 1)),
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

COLLECTION_JOBS_SCHEMA = """
CREATE TABLE collection_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'done', 'error')),
    saved_count INTEGER NOT NULL DEFAULT 0 CHECK(saved_count >= 0),
    discovered_count INTEGER NOT NULL DEFAULT 0 CHECK(discovered_count >= 0),
    analyzed_count INTEGER NOT NULL DEFAULT 0 CHECK(analyzed_count >= 0),
    accepted_count INTEGER NOT NULL DEFAULT 0 CHECK(accepted_count >= 0),
    rejected_count INTEGER NOT NULL DEFAULT 0 CHECK(rejected_count >= 0),
    invalid_distribution_count INTEGER NOT NULL DEFAULT 0 CHECK(invalid_distribution_count >= 0),
    discovery_methods TEXT NOT NULL DEFAULT '[]',
    message TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT NOT NULL DEFAULT ''
)
"""
COLLECTION_JOB_STATUSES = ("pending", "running", "done", "error")

INITIAL_SCHEMA_STATEMENTS = (
    DATA_SOURCES_SCHEMA,
    COLLECTED_DATASETS_SCHEMA,
    COLLECTED_DISTRIBUTIONS_SCHEMA,
    COLLECTION_JOBS_SCHEMA,
)
MANAGED_TABLES = (
    "data_sources",
    "collected_datasets",
    "collected_distributions",
    "collection_jobs",
)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        _apply_schema_migrations(connection)
        _assert_seed_sources_can_be_applied(connection)
        _seed_data_sources(connection)


def list_data_sources() -> list[dict[str, int | str]]:
    with get_connection() as connection:
        _require_current_schema(connection)
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
        _require_current_schema(connection)
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
    if source_key in RESERVED_DATA_SOURCE_KEYS:
        raise ReservedDataSourceKeyError(
            f"Data source key {source_key!r} is reserved by the application."
        )

    with get_connection() as connection:
        _require_current_schema(connection)
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
        _require_current_schema(connection)
        for dataset in datasets:
            row = _upsert_collected_dataset(connection, source_url, dataset)
            dataset_id = int(row["id"])
            validation_by_distribution_key = _validation_results_by_distribution_key(
                dataset.validation_results
            )
            for distribution in dataset.distributions:
                _upsert_collected_distribution(
                    connection,
                    dataset_id,
                    distribution,
                    validation_by_distribution_key.get(
                        (distribution.url, distribution.format)
                    ),
                )

            distribution_rows = connection.execute(
                """
                SELECT *
                FROM collected_distributions
                WHERE dataset_id = ?
                ORDER BY probability DESC, url
                """,
                (dataset_id,),
            ).fetchall()
            saved_datasets.append(
                _collected_dataset_from_rows(row, distribution_rows)
            )

    return saved_datasets


def list_collected_datasets() -> list[CollectedDataset]:
    with get_connection() as connection:
        _require_current_schema(connection)
        dataset_rows = connection.execute(
            """
            SELECT id, source_url, dataset_url, title, description, publisher,
                   hosting_platform, uploader, discovery_method,
                   dataset_probability, dataset_signals, health_probability,
                   health_label, health_signals, first_seen_at, last_seen_at,
                   updated_at
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


def create_collection_job(source_url: str) -> dict[str, object]:
    with get_connection() as connection:
        _require_current_schema(connection)
        cursor = connection.execute(
            """
            INSERT INTO collection_jobs (source_url, status, message)
            VALUES (?, 'pending', 'Collecte en attente.')
            """,
            (source_url,),
        )
        row = _get_collection_job_row(connection, int(cursor.lastrowid))

    return _collection_job_to_dict(row)


def get_collection_job(job_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        _require_current_schema(connection)
        row = _get_collection_job_row(connection, job_id)

    return _collection_job_to_dict(row) if row else None


def mark_collection_job_running(job_id: int) -> dict[str, object] | None:
    with get_connection() as connection:
        _require_current_schema(connection)
        connection.execute(
            """
            UPDATE collection_jobs
            SET status = 'running',
                saved_count = 0,
                discovered_count = 0,
                analyzed_count = 0,
                accepted_count = 0,
                rejected_count = 0,
                invalid_distribution_count = 0,
                discovery_methods = '[]',
                message = 'Collecte en cours.',
                error = '',
                updated_at = CURRENT_TIMESTAMP,
                finished_at = ''
            WHERE id = ?
            """,
            (job_id,),
        )
        row = _get_collection_job_row(connection, job_id)

    return _collection_job_to_dict(row) if row else None


def mark_collection_job_done(
    job_id: int,
    saved_count: int,
    report: CollectionReport | None = None,
) -> dict[str, object] | None:
    report = report or CollectionReport()
    message = _collection_job_done_message(saved_count, report)
    with get_connection() as connection:
        _require_current_schema(connection)
        connection.execute(
            """
            UPDATE collection_jobs
            SET status = 'done',
                saved_count = ?,
                discovered_count = ?,
                analyzed_count = ?,
                accepted_count = ?,
                rejected_count = ?,
                invalid_distribution_count = ?,
                discovery_methods = ?,
                message = ?,
                error = '',
                updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                saved_count,
                report.discovered_count,
                report.analyzed_count,
                report.accepted_count,
                report.rejected_count,
                report.invalid_distribution_count,
                _serialize_discovery_methods(report.discovery_methods),
                message,
                job_id,
            ),
        )
        row = _get_collection_job_row(connection, job_id)

    return _collection_job_to_dict(row) if row else None


def mark_collection_job_error(
    job_id: int,
    error: str,
) -> dict[str, object] | None:
    with get_connection() as connection:
        _require_current_schema(connection)
        connection.execute(
            """
            UPDATE collection_jobs
            SET status = 'error',
                message = 'Collecte échouée.',
                error = ?,
                updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error, job_id),
        )
        row = _get_collection_job_row(connection, job_id)

    return _collection_job_to_dict(row) if row else None


# Version 1 is the initial application schema. Because this project has no
# production legacy database yet, unversioned databases with managed tables are
# rejected instead of guessed and rebuilt.
def _apply_schema_migrations(connection: sqlite3.Connection) -> None:
    version = _schema_version(connection)
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported "
            f"version {CURRENT_SCHEMA_VERSION}."
        )

    while version < CURRENT_SCHEMA_VERSION:
        source_version = version
        target_version = version + 1
        _run_schema_migration(
            connection,
            source_version,
            target_version,
            _migration_for_version(version),
        )
        version = _schema_version(connection)
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}."
            )
        if version < target_version:
            raise RuntimeError(
                f"Migration to schema version {target_version} did not complete."
            )

    _assert_foreign_key_integrity(connection)


def _migration_for_version(version: int):
    if version == 0:
        return _migrate_0_to_1

    raise RuntimeError(f"No migration registered for schema version {version}.")


def _run_schema_migration(
    connection: sqlite3.Connection,
    source_version: int,
    target_version: int,
    migration,
) -> None:
    if connection.in_transaction:
        raise RuntimeError("Cannot run schema migration inside an active transaction.")

    try:
        connection.execute("BEGIN IMMEDIATE")
        locked_version = _schema_version(connection)
        if locked_version != source_version:
            connection.commit()
            return

        migration(connection)
        _assert_foreign_key_integrity(connection)
        _set_schema_version(connection, target_version)
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def _migrate_0_to_1(connection: sqlite3.Connection) -> None:
    existing_tables = _existing_managed_tables(connection)
    if existing_tables:
        raise RuntimeError(
            "Unversioned database already contains managed tables: "
            f"{', '.join(existing_tables)}. Start with an empty database or add "
            "an explicit migration for this historical schema."
        )

    for schema in INITIAL_SCHEMA_STATEMENTS:
        connection.execute(schema)


def _existing_managed_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        table_name
        for table_name in MANAGED_TABLES
        if _table_exists(connection, table_name)
    )


def _assert_seed_sources_can_be_applied(connection: sqlite3.Connection) -> None:
    seed_sources_by_key = {source["source_key"]: source for source in DATA_SOURCE_SEEDS}
    if not seed_sources_by_key or not _table_exists(connection, "data_sources"):
        return

    placeholders = ", ".join("?" for _ in seed_sources_by_key)
    rows = connection.execute(
        f"""
        SELECT id, source_key, name, description, theme, page_url
        FROM data_sources
        WHERE source_key IN ({placeholders})
        """,
        tuple(seed_sources_by_key),
    ).fetchall()
    for row in rows:
        seed = seed_sources_by_key[str(row["source_key"])]
        if _data_source_row_matches_seed(row, seed):
            continue

        raise RuntimeError(
            "Cannot safely seed data_sources. "
            f"Row id={row['id']} uses reserved source_key "
            f"{str(row['source_key'])!r} but does not match the application "
            "seed. Seeding would overwrite existing data."
        )


def _data_source_row_matches_seed(
    row: sqlite3.Row,
    seed: dict[str, str],
) -> bool:
    return _data_source_values_match_seed(
        str(row["name"]),
        str(row["description"]),
        str(row["theme"]),
        str(row["page_url"]),
        seed,
    )


def _data_source_values_match_seed(
    name: str,
    description: str,
    theme: str,
    page_url: str,
    seed: dict[str, str],
) -> bool:
    return (
        name == seed["name"]
        and description == seed["description"]
        and theme == seed["theme"]
        and page_url == seed["page_url"]
    )


def _seed_data_sources(connection: sqlite3.Connection) -> None:
    # Seed source keys are application-owned identifiers. User-created sources
    # must use distinct source_key values; matching seed keys may be refreshed.
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


def _require_current_schema(connection: sqlite3.Connection) -> None:
    version = _schema_version(connection)
    if version == CURRENT_SCHEMA_VERSION:
        return
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported "
            f"version {CURRENT_SCHEMA_VERSION}."
        )

    raise RuntimeError(
        f"Database schema version {version} is not initialized. "
        "Run init_database() before database operations."
    )


def _schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _set_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version = {version}")


def _assert_foreign_key_integrity(connection: sqlite3.Connection) -> None:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        formatted = [tuple(violation) for violation in violations]
        raise RuntimeError(
            f"Database foreign key integrity check failed: {formatted}"
        )


def _get_collection_job_row(
    connection: sqlite3.Connection,
    job_id: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, source_url, status, saved_count, discovered_count,
               analyzed_count, accepted_count, rejected_count,
               invalid_distribution_count, discovery_methods, message, error,
               created_at, updated_at, finished_at
        FROM collection_jobs
        WHERE id = ?
        """,
        (job_id,),
    ).fetchone()


def _collection_job_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "source_url": str(row["source_url"]),
        "status": str(row["status"]),
        "saved_count": int(row["saved_count"]),
        "discovered_count": int(row["discovered_count"]),
        "analyzed_count": int(row["analyzed_count"]),
        "accepted_count": int(row["accepted_count"]),
        "rejected_count": int(row["rejected_count"]),
        "invalid_distribution_count": int(row["invalid_distribution_count"]),
        "discovery_methods": _deserialize_discovery_methods(str(row["discovery_methods"])),
        "message": str(row["message"]),
        "error": str(row["error"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "finished_at": str(row["finished_at"]),
    }


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
            dataset_signals, health_probability, health_label, health_signals,
            first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
            last_seen_at = CURRENT_TIMESTAMP,
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
               first_seen_at, last_seen_at, updated_at
        FROM collected_datasets
        WHERE dataset_url = ?
        """,
        (dataset.dataset_url,),
    ).fetchone()


def _validation_results_by_distribution_key(
    validation_results: list[ValidationResult],
) -> dict[tuple[str, str], ValidationResult]:
    validation_by_distribution_key: dict[tuple[str, str], ValidationResult] = {}
    for validation in validation_results:
        key = (validation.url, validation.format)
        if key in validation_by_distribution_key:
            raise ValueError(
                "Duplicate validation result for distribution "
                f"url={validation.url!r}, format={validation.format!r}."
            )
        validation_by_distribution_key[key] = validation

    return validation_by_distribution_key


def _upsert_collected_distribution(
    connection: sqlite3.Connection,
    dataset_id: int,
    distribution: DistributionCandidate,
    validation: ValidationResult | None,
) -> None:
    # validation_attempted means the distribution has been checked at least once.
    # Crawls that see the distribution without revalidating it preserve the last
    # validation result and its last_checked_at timestamp.
    validation_attempted = int(validation is not None)
    connection.execute(
        """
        INSERT INTO collected_distributions (
            dataset_id, url, format, probability, anchor, extension, mime_type,
            nearby_text, same_domain, dom_path, signals, first_seen_at, last_seen_at,
            last_checked_at, validation_attempted, validation_final_url, validation_ok,
            validation_http_status, validation_mime_type, validation_size_bytes,
            validation_etag, validation_last_modified, validation_content_disposition,
            validation_error
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE '' END,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(dataset_id, url, format) DO UPDATE SET
            probability = excluded.probability,
            anchor = excluded.anchor,
            extension = excluded.extension,
            mime_type = excluded.mime_type,
            nearby_text = excluded.nearby_text,
            same_domain = excluded.same_domain,
            dom_path = excluded.dom_path,
            signals = excluded.signals,
            last_seen_at = CURRENT_TIMESTAMP,
            last_checked_at = CASE
                WHEN excluded.validation_attempted = 1 THEN CURRENT_TIMESTAMP
                ELSE collected_distributions.last_checked_at
            END,
            validation_attempted = CASE
                WHEN excluded.validation_attempted = 1 THEN 1
                ELSE collected_distributions.validation_attempted
            END,
            validation_final_url = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_final_url
                ELSE collected_distributions.validation_final_url
            END,
            validation_ok = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_ok
                ELSE collected_distributions.validation_ok
            END,
            validation_http_status = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_http_status
                ELSE collected_distributions.validation_http_status
            END,
            validation_mime_type = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_mime_type
                ELSE collected_distributions.validation_mime_type
            END,
            validation_size_bytes = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_size_bytes
                ELSE collected_distributions.validation_size_bytes
            END,
            validation_etag = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_etag
                ELSE collected_distributions.validation_etag
            END,
            validation_last_modified = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_last_modified
                ELSE collected_distributions.validation_last_modified
            END,
            validation_content_disposition = CASE
                WHEN excluded.validation_attempted = 1
                    THEN excluded.validation_content_disposition
                ELSE collected_distributions.validation_content_disposition
            END,
            validation_error = CASE
                WHEN excluded.validation_attempted = 1 THEN excluded.validation_error
                ELSE collected_distributions.validation_error
            END
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
            validation_attempted,
            validation_attempted,
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
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
            last_checked_at=str(row["last_checked_at"]),
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
        if bool(row["validation_attempted"])
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
        first_seen_at=str(dataset_row["first_seen_at"]),
        last_seen_at=str(dataset_row["last_seen_at"]),
        updated_at=str(dataset_row["updated_at"]),
    )


def _collection_job_done_message(saved_count: int, report: CollectionReport) -> str:
    if saved_count:
        return f"{saved_count} dataset(s) sauvegardé(s)."
    if report.discovered_count == 0:
        return "Aucune URL candidate découverte."
    if report.analyzed_count == 0:
        return "Aucune page analysée."
    return "Aucun dataset santé avec fichier valide trouvé."


def _serialize_discovery_methods(discovery_methods: tuple[str, ...]) -> str:
    return json.dumps(list(discovery_methods), sort_keys=True)


def _deserialize_discovery_methods(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exception:
        logger.warning("Invalid JSON in stored discovery methods: %s", exception)
        return []

    if not isinstance(data, list):
        logger.warning(
            "Invalid discovery methods JSON type: expected list, got %s",
            type(data).__name__,
        )
        return []

    invalid_indexes = [
        index for index, item in enumerate(data) if not isinstance(item, str)
    ]
    if invalid_indexes:
        logger.warning(
            "Invalid discovery methods JSON items ignored at indexes: %s",
            invalid_indexes,
        )

    return [item for item in data if isinstance(item, str)]


def _serialize_signals(signals: dict[str, object]) -> str:
    return json.dumps(signals, sort_keys=True)


def _deserialize_signals(value: str) -> dict[str, object]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exception:
        logger.warning("Invalid JSON in stored signals: %s", exception)
        return {}

    if not isinstance(data, dict):
        logger.warning(
            "Invalid signals JSON type: expected dict, got %s",
            type(data).__name__,
        )
        return {}

    return data
