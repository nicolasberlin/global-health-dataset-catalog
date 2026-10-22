from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from .connection import (
    _fetchall,
    _fetchone,
    _require_database_initialized,
    _require_database_pool,
    _set_initialized_pool,
)
from .migrations import migration_for_version
from .migrations.v001 import (
    DATASET_SEARCH_TEXT_CONFIGURATION as DATASET_SEARCH_TEXT_CONFIGURATION,
)
from .migrations.v001 import MANAGED_TABLES

# One complete baseline initializes an empty database; existing data is preserved.
CURRENT_SCHEMA_VERSION = 1
OBSOLETE_COLLECTED_DATASET_COLUMNS = (
    "dataset_probability",
    "health_probability",
    "health_label",
)

SCHEMA_MIGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY CHECK(version >= 0),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

REPOSITORY_PERSISTENCE_COLUMNS = {
    "search_sessions": {
        "errors",
        "local_result_count",
        "discovery_complete",
        "execution_mode",
        "access_mode",
        "client_key",
        "attempt_number",
        "attempt_token",
        "online_quota_attempt",
        "warnings",
        "retry_at",
        "id",
        "owner_id",
        "query",
        "origin",
        "status",
        "error",
        "finished_at",
    },
    "api_rate_limits": {
        "owner_id",
        "operation",
        "window_started_at",
        "request_count",
    },
    "repository_candidates": {
        "errors",
        "id",
        "search_session_id",
        "url",
        "classification_status",
        "classification",
        "error",
    },
    "collection_jobs": {
        "kind",
        "repository_candidate_id",
        "errors",
        "outcome",
        "collection_deadline_at",
        "collection_coverage",
        "collection_method_summary",
    },
    "classification_votes": {"errors"},
    "classification_vote_attempts": {"run_id", "voter_id", "attempt", "model", "error", "evidence"},
    "collection_method_attempts": {"job_id", "claim_version", "sequence", "observation"},
    "collection_resource_checks": {"method_id", "resource_key", "observation"},
    "api_commands": {"owner_id", "command_key", "fingerprint", "result"},
    "worker_claims": {"token", "queue", "resource_id", "claim_version"},
    "application_ownership": {"singleton", "generation"},
    "search_local_results": {"search_id", "dataset_id", "position"},
    "collection_job_candidates": {"job_id", "candidate_id"},
}
for _table in ("repository_candidates", "collection_jobs"):
    REPOSITORY_PERSISTENCE_COLUMNS[_table].update(
        {
            "retry_cycle",
            "retry_round",
            "retry_started_at",
            "next_retry_at",
        }
    )
REPOSITORY_PERSISTENCE_COLUMNS["classification_votes"].update(
    {
        "retry_cycle",
        "cycle_attempts",
        "last_attempt_token",
    }
)
REPOSITORY_PERSISTENCE_COLUMNS["collected_datasets"] = {"record_identity"}

REPOSITORY_PERSISTENCE_INDEXES = {
    "candidate_retry_due_idx",
    "collection_retry_due_idx",
    "dataset_discovery_observations_source_idx",
    "collection_job_candidates_candidate_latest_idx",
    "collection_method_claim_page_idx",
    "collection_jobs_active_repository_candidate_idx",
    "collection_jobs_active_repository_url_idx",
}


async def init_database() -> None:
    pool = _require_database_pool()
    _set_initialized_pool(None)
    async with pool.connection() as connection:
        await _apply_schema_migrations(connection)
    _set_initialized_pool(pool)


async def validate_database_schema() -> None:
    """Initialize a runtime pool using an already migrated schema, without DDL."""
    pool = _require_database_pool()
    _set_initialized_pool(None)
    async with pool.connection() as connection:
        version = await _schema_version(connection)
        if version != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} does not match required version "
                f"{CURRENT_SCHEMA_VERSION}. Run the explicit migration command first."
            )
        await _validate_schema_contracts(connection)
    _set_initialized_pool(pool)


async def _apply_schema_migrations(connection: AsyncConnection[DictRow]) -> None:
    version = await _schema_version(connection)
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported "
            f"version {CURRENT_SCHEMA_VERSION}. This release uses a fresh baseline; "
            "recreate the development database explicitly before starting it."
        )

    while version < CURRENT_SCHEMA_VERSION:
        source_version = version
        target_version = version + 1
        await _run_schema_migration(
            connection,
            source_version,
            target_version,
            _migration_for_version(version),
        )
        version = await _schema_version(connection)
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}. This release uses a fresh baseline; "
                "recreate the development database explicitly before starting it."
            )
        if version < target_version:
            raise RuntimeError(f"Migration to schema version {target_version} did not complete.")

    await _validate_schema_contracts(connection)


async def _validate_schema_contracts(connection: AsyncConnection[DictRow]) -> None:
    await _assert_current_schema_tables_exist(connection)
    await _assert_current_schema_repository_persistence_exists(connection)
    await _assert_current_schema_has_no_obsolete_columns(connection)
    await _assert_current_schema_search_index_exists(connection)


def _migration_for_version(version: int):
    return migration_for_version(version)


async def _run_schema_migration(
    connection: AsyncConnection[DictRow],
    source_version: int,
    target_version: int,
    migration,
) -> None:
    async with connection.transaction():
        await connection.execute("SET LOCAL statement_timeout = '120s'")
        await connection.execute("SET LOCAL lock_timeout = '30s'")
        if source_version == 0:
            # The table lock does not exist yet on a fresh database. Serialize its
            # creation too, so concurrent initializers can safely recheck version.
            await connection.execute(
                """
                SELECT pg_advisory_xact_lock(hashtextextended(
                    current_database() || ':' || current_schema() || ':schema_migrations', 0
                ))
                """
            )
            await connection.execute(SCHEMA_MIGRATIONS_SCHEMA)
        await connection.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
        locked_version = await _schema_version(connection)
        if locked_version != source_version:
            return

        if source_version == 0:
            await _assert_database_can_be_initialized(connection)
        await migration(connection)
        await _set_schema_version(connection, target_version)


async def _assert_database_can_be_initialized(
    connection: AsyncConnection[DictRow],
) -> None:
    existing_tables = await _existing_managed_tables(connection)
    if existing_tables:
        raise RuntimeError(
            "Database contains unmanaged application tables: "
            f"{', '.join(existing_tables)}. Start with an empty PostgreSQL "
            "database. This release does not upgrade historical schemas or delete their data."
        )


async def _existing_managed_tables(
    connection: AsyncConnection[DictRow],
) -> tuple[str, ...]:
    existing_tables = []
    for table_name in MANAGED_TABLES:
        if await _table_exists(connection, table_name):
            existing_tables.append(table_name)
    return tuple(existing_tables)


async def _missing_managed_tables(
    connection: AsyncConnection[DictRow],
) -> tuple[str, ...]:
    missing_tables = []
    for table_name in MANAGED_TABLES:
        if not await _table_exists(connection, table_name):
            missing_tables.append(table_name)
    return tuple(missing_tables)


async def _assert_current_schema_tables_exist(
    connection: AsyncConnection[DictRow],
) -> None:
    missing_tables = await _missing_managed_tables(connection)
    if missing_tables:
        raise RuntimeError(
            f"Database schema version {CURRENT_SCHEMA_VERSION} is recorded, "
            "but managed tables are missing: "
            f"{', '.join(missing_tables)}. Recreate the local database."
        )


async def _assert_current_schema_repository_persistence_exists(
    connection: AsyncConnection[DictRow],
) -> None:
    missing_contracts: list[str] = []
    for table_name, required_columns in REPOSITORY_PERSISTENCE_COLUMNS.items():
        rows = await _fetchall(
            connection,
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
            """,
            (table_name,),
        )
        existing_columns = {str(row["column_name"]) for row in rows}
        missing_contracts.extend(
            f"{table_name}.{column_name}"
            for column_name in sorted(required_columns - existing_columns)
        )

    index_rows = await _fetchall(
        connection,
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = current_schema()
          AND indexname = ANY(%s)
        """,
        (list(REPOSITORY_PERSISTENCE_INDEXES),),
    )
    existing_indexes = {str(row["indexname"]) for row in index_rows}
    missing_contracts.extend(sorted(REPOSITORY_PERSISTENCE_INDEXES - existing_indexes))

    if missing_contracts:
        raise RuntimeError(
            f"Database schema version {CURRENT_SCHEMA_VERSION} is obsolete; "
            "repository persistence contracts are missing: "
            f"{', '.join(missing_contracts)}. Recreate the local database."
        )


async def _assert_current_schema_has_no_obsolete_columns(
    connection: AsyncConnection[DictRow],
) -> None:
    rows = await _fetchall(
        connection,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'collected_datasets'
        """,
    )
    existing_columns = {str(row["column_name"]) for row in rows}
    obsolete_columns = sorted(existing_columns.intersection(OBSOLETE_COLLECTED_DATASET_COLUMNS))
    if obsolete_columns:
        raise RuntimeError(
            f"Database schema version {CURRENT_SCHEMA_VERSION} is obsolete; "
            "collected_datasets still contains removed columns: "
            f"{', '.join(obsolete_columns)}. Recreate the local database."
        )


async def _assert_current_schema_search_index_exists(
    connection: AsyncConnection[DictRow],
) -> None:
    column_row = await _fetchone(
        connection,
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'collected_datasets'
              AND column_name = 'search_vector'
              AND data_type = 'tsvector'
        ) AS column_exists
        """,
    )
    index_row = await _fetchone(
        connection,
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'collected_datasets'
              AND indexname = 'collected_datasets_search_vector_idx'
        ) AS index_exists
        """,
    )
    if (
        column_row is None
        or not bool(column_row["column_exists"])
        or index_row is None
        or not bool(index_row["index_exists"])
    ):
        raise RuntimeError(
            f"Database schema version {CURRENT_SCHEMA_VERSION} is recorded, "
            "but the collected dataset search index is missing."
        )


async def _table_exists(
    connection: AsyncConnection[DictRow],
    table_name: str,
) -> bool:
    row = await _fetchone(
        connection,
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = %s
        ) AS table_exists
        """,
        (table_name,),
    )
    return row is not None and bool(row["table_exists"])


async def _require_current_schema(connection: AsyncConnection[DictRow]) -> None:
    """Startup validates the schema once for this pool; business calls do no SQL here."""
    _require_database_initialized()


async def _schema_version(connection: AsyncConnection[DictRow]) -> int:
    if not await _table_exists(connection, "schema_migrations"):
        return 0

    row = await _fetchone(
        connection,
        "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations",
    )
    if row is None:
        return 0
    return int(row["version"])


async def _set_schema_version(
    connection: AsyncConnection[DictRow],
    version: int,
) -> None:
    await connection.execute(
        """
        INSERT INTO schema_migrations (version)
        VALUES (%s)
        ON CONFLICT(version) DO NOTHING
        """,
        (version,),
    )
