from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from app.db import connection as db_connection
from app.db import schema as db_schema
from app.db import serialization as db_serialization
from psycopg import sql as pg_sql

from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    DistributionCandidate,
    ValidationResult,
)

pytestmark = pytest.mark.anyio

SCHEMA_TABLES = (
    "schema_migrations",
    "data_sources",
    "collected_datasets",
    "collected_distributions",
    "dataset_discovery_observations",
    "collection_jobs",
)


async def _schema_version(database) -> int:
    async with db_connection._require_database_pool().connection() as connection:
        return await db_schema._schema_version(connection)


async def _table_names(database) -> set[str]:
    async with db_connection._require_database_pool().connection() as connection:
        rows = await db_connection._fetchall(
            connection,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
            """,
        )
    return {str(row["table_name"]) for row in rows}


async def _fetchall(database, sql: str, parameters=None):
    async with db_connection._require_database_pool().connection() as connection:
        return await db_connection._fetchall(connection, sql, parameters)


async def _execute(database, sql: str, parameters=None) -> None:
    async with db_connection._require_database_pool().connection() as connection:
        await connection.execute(sql, parameters)


async def _insert_minimal_dataset(database, suffix: str = "") -> int:
    async with db_connection._require_database_pool().connection() as connection:
        row = await db_connection._fetchone(
            connection,
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                f"https://catalog.example.org/dataset/valid{suffix}",
                "Valid dataset",
                0.8,
                0.7,
                "HEALTH",
            ),
        )
    return int(row["id"])


async def _assert_schema_constraints_are_enforced(database, suffix: str = "") -> None:
    dataset_id = await _insert_minimal_dataset(database, suffix)
    invalid_statements = [
        (
            """
            INSERT INTO data_sources (
                source_key, name, description, theme, page_url
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            ("", "Empty source key", "", "General", "https://example.org/"),
        ),
        (
            """
            INSERT INTO data_sources (
                source_key, name, description, theme, page_url
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                "My HDX",
                "Invalid source key",
                "",
                "General",
                "https://example.org/",
            ),
        ),
        (
            """
            INSERT INTO data_sources (
                source_key, name, description, theme, page_url
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            ("empty_page_url", "Empty page URL", "", "General", ""),
        ),
        (
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                "   ",
                "Blank dataset URL",
                0.8,
                0.7,
                "HEALTH",
            ),
        ),
        (
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, dataset_signals,
                health_probability, health_label
            )
            VALUES (%s, %s, %s, '[]'::jsonb, %s, %s)
            """,
            (
                f"https://catalog.example.org/dataset/bad-dataset-signals{suffix}",
                "Bad dataset signals",
                0.8,
                0.7,
                "HEALTH",
            ),
        ),
        (
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, geography,
                health_probability, health_label
            )
            VALUES (%s, %s, %s, '{}'::jsonb, %s, %s)
            """,
            (
                f"https://catalog.example.org/dataset/bad-origin-countries{suffix}",
                "Bad origin countries",
                0.8,
                0.7,
                "HEALTH",
            ),
        ),
        (
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label, health_signals
            )
            VALUES (%s, %s, %s, %s, %s, '[]'::jsonb)
            """,
            (
                f"https://catalog.example.org/dataset/bad-health-signals{suffix}",
                "Bad health signals",
                0.8,
                0.7,
                "HEALTH",
            ),
        ),
        (
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                f"https://catalog.example.org/dataset/bad-probability{suffix}",
                "Bad dataset probability",
                16.42,
                0.7,
                "HEALTH",
            ),
        ),
        (
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                f"https://catalog.example.org/dataset/bad-label{suffix}",
                "Bad health label",
                0.8,
                0.7,
                "banana",
            ),
        ),
        (
            """
            INSERT INTO collected_distributions (
                dataset_id, url, format, probability
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                dataset_id,
                "   ",
                "CSV",
                0.9,
            ),
        ),
        (
            """
            INSERT INTO collected_distributions (
                dataset_id, url, format, probability
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                dataset_id,
                f"https://catalog.example.org/files/blank-format{suffix}.csv",
                "   ",
                0.9,
            ),
        ),
        (
            """
            INSERT INTO collected_distributions (
                dataset_id, url, format, probability, signals
            )
            VALUES (%s, %s, %s, %s, '[]'::jsonb)
            """,
            (
                dataset_id,
                f"https://catalog.example.org/files/bad-signals{suffix}.csv",
                "CSV",
                0.9,
            ),
        ),
        (
            """
            INSERT INTO collected_distributions (
                dataset_id, url, format, probability
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                999_999,
                f"https://catalog.example.org/files/bad-fk{suffix}.csv",
                "CSV",
                0.9,
            ),
        ),
        (
            """
            INSERT INTO collected_distributions (
                dataset_id, url, format, probability
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                dataset_id,
                f"https://catalog.example.org/files/bad-probability{suffix}.csv",
                "CSV",
                4.2,
            ),
        ),
        (
            """
            INSERT INTO collection_jobs (source_url)
            VALUES (%s)
            """,
            ("",),
        ),
        (
            """
            INSERT INTO collection_jobs (source_url, status)
            VALUES (%s, %s)
            """,
            (f"https://catalog.example.org/bad-status{suffix}", "banana"),
        ),
        (
            """
            INSERT INTO collection_jobs (source_url, saved_count)
            VALUES (%s, %s)
            """,
            (f"https://catalog.example.org/bad-saved-count{suffix}", -1),
        ),
    ]

    for sql, parameters in invalid_statements:
        with pytest.raises(psycopg.Error):
            await _execute(database, sql, parameters)


def _mortality_dataset() -> CollectedDataset:
    return CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/mortality",
        title="Mortality health dataset",
        description="Official mortality health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        geography=("France",),
        dataset_probability=0.92,
        dataset_signals={"schema_dataset": True},
        health_probability=0.8,
        health_label="HEALTH",
        health_signals={"matched_keywords": ["mortality"]},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/mortality.csv",
                format="CSV",
                probability=0.95,
                anchor="CSV download",
                mime_type="text/csv",
                signals={"ckan_resource": True},
            )
        ],
        discovery_method="ckan",
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/files/mortality.csv",
                final_url="https://catalog.example.org/files/mortality.csv",
                format="CSV",
                ok=True,
                http_status=200,
                mime_type="text/csv",
                size_bytes=123,
            )
        ],
    )


async def test_init_database_seeds_dataset_pages(database):
    await database.init_database()

    sources = await database.list_data_sources()
    assert len(sources) == 2
    assert {source["source_key"] for source in sources} == {
        "who_gho_indicators",
        "who_gho_life_expectancy",
    }
    assert all(source["page_url"].startswith("https://www.who.int/") for source in sources)
    assert {source["theme"] for source in sources} == {"General", "Mortality"}
    assert await _schema_version(database) == db_schema.CURRENT_SCHEMA_VERSION

    await database.upsert_collector_data_source(
        "user_defined_source",
        "User source",
        "User description",
        "Custom",
        "https://example.org/user-source",
    )
    await database.init_database()

    sources = await database.list_data_sources()
    life_expectancy_source = next(
        source
        for source in sources
        if source["source_key"] == "who_gho_life_expectancy"
    )
    assert (
        life_expectancy_source["name"]
        == "WHO Global Health Observatory - Life expectancy"
    )
    assert any(source["source_key"] == "user_defined_source" for source in sources)
    assert len(sources) == 3


async def test_init_database_creates_current_schema_with_integrity(database):
    await database.init_database()

    assert await _schema_version(database) == db_schema.CURRENT_SCHEMA_VERSION
    assert set(SCHEMA_TABLES).issubset(await _table_names(database))
    await _assert_schema_constraints_are_enforced(database, "-fresh")


async def test_table_exists_checks_current_schema_only(database):
    table_name = f"shadow_only_{uuid.uuid4().hex}"
    shadow_schema = f"shadow_{uuid.uuid4().hex}"

    async with db_connection._require_database_pool().connection() as connection:
        current_schema_row = await db_connection._fetchone(
            connection,
            "SELECT current_schema() AS schema_name",
        )
        current_schema = str(current_schema_row["schema_name"])

        try:
            await connection.execute(
                pg_sql.SQL("CREATE SCHEMA {}").format(pg_sql.Identifier(shadow_schema))
            )
            await connection.execute(
                pg_sql.SQL("CREATE TABLE {}.{} (id integer)").format(
                    pg_sql.Identifier(shadow_schema),
                    pg_sql.Identifier(table_name),
                )
            )
            await connection.execute(
                pg_sql.SQL("SET LOCAL search_path TO {}, {}").format(
                    pg_sql.Identifier(current_schema),
                    pg_sql.Identifier(shadow_schema),
                )
            )

            assert await db_schema._table_exists(connection, table_name) is False
        finally:
            await connection.execute(
                pg_sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    pg_sql.Identifier(shadow_schema)
                )
            )


async def test_seen_timestamps_default_to_postgres_timestamps(database):
    await database.init_database()

    dataset_id = await _insert_minimal_dataset(database, "-timestamps")
    await _execute(
        database,
        """
        INSERT INTO collected_distributions (
            dataset_id, url, format, probability
        )
        VALUES (%s, %s, %s, %s)
        """,
        (
            dataset_id,
            "https://catalog.example.org/files/default-timestamps.csv",
            "CSV",
            0.9,
        ),
    )
    dataset_rows = await _fetchall(
        database,
        """
        SELECT first_seen_at, last_seen_at
        FROM collected_datasets
        WHERE id = %s
        """,
        (dataset_id,),
    )
    distribution_rows = await _fetchall(
        database,
        """
        SELECT first_seen_at, last_seen_at, last_checked_at
        FROM collected_distributions
        WHERE dataset_id = %s
        """,
        (dataset_id,),
    )

    assert dataset_rows[0]["first_seen_at"] is not None
    assert dataset_rows[0]["last_seen_at"] is not None
    assert distribution_rows[0]["first_seen_at"] is not None
    assert distribution_rows[0]["last_seen_at"] is not None
    assert distribution_rows[0]["last_checked_at"] is None


async def test_init_database_preserves_unrelated_accounts_table(database):
    await _execute(
        database,
        """
        CREATE TABLE accounts (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            email TEXT NOT NULL
        )
        """,
    )
    await _execute(
        database,
        "INSERT INTO accounts (email) VALUES (%s)",
        ("admin@example.org",),
    )

    await database.init_database()

    account_rows = await _fetchall(database, "SELECT email FROM accounts")
    assert [row["email"] for row in account_rows] == ["admin@example.org"]
    assert set(SCHEMA_TABLES).issubset(await _table_names(database))


async def test_init_database_rejects_unversioned_managed_tables_without_data_loss(
    database,
):
    await _execute(
        database,
        """
        CREATE TABLE data_sources (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL
        )
        """,
    )
    await _execute(database, "INSERT INTO data_sources (name) VALUES (%s)", ("Legacy",))

    with pytest.raises(RuntimeError, match="unmanaged application tables"):
        await database.init_database()

    rows = await _fetchall(database, "SELECT name FROM data_sources")
    assert [row["name"] for row in rows] == ["Legacy"]
    assert "schema_migrations" not in await _table_names(database)
    assert "collected_datasets" not in await _table_names(database)
    assert await _schema_version(database) == 0


async def test_init_database_rejects_current_version_with_missing_managed_tables(
    database,
):
    async with db_connection._require_database_pool().connection() as connection:
        await connection.execute(db_schema.SCHEMA_MIGRATIONS_SCHEMA)
        await db_schema._set_schema_version(
            connection,
            db_schema.CURRENT_SCHEMA_VERSION,
        )

    with pytest.raises(RuntimeError, match="managed tables are missing") as error:
        await database.init_database()

    assert "data_sources" in str(error.value)
    assert "collection_jobs" in str(error.value)


async def test_init_database_does_not_overwrite_current_reserved_source_key_collision(
    database,
):
    async with db_connection._require_database_pool().connection() as connection:
        await connection.execute(db_schema.SCHEMA_MIGRATIONS_SCHEMA)
        for schema in db_schema.INITIAL_SCHEMA_STATEMENTS:
            await connection.execute(schema)
        await connection.execute(
            """
            INSERT INTO data_sources (source_key, name, description, theme, page_url)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                "who_gho_life_expectancy",
                "Custom life expectancy source",
                "Already at current schema.",
                "Custom",
                "https://example.org/current-collision",
            ),
        )
        await db_schema._set_schema_version(
            connection,
            db_schema.CURRENT_SCHEMA_VERSION,
        )

    await database.init_database()

    rows = await _fetchall(
        database,
        """
        SELECT name, page_url
        FROM data_sources
        WHERE source_key = %s
        """,
        ("who_gho_life_expectancy",),
    )
    assert rows[0]["name"] == "Custom life expectancy source"
    assert rows[0]["page_url"] == "https://example.org/current-collision"


async def test_future_seed_collision_preserves_existing_source(database, monkeypatch):
    from app.db import schema as db_schema

    await database.init_database()
    await database.upsert_collector_data_source(
        "who_mortality_2027",
        "User mortality source",
        "Created before the key became a seed.",
        "Custom",
        "https://example.org/user-mortality",
    )
    future_seed = {
        "source_key": "who_mortality_2027",
        "name": "WHO mortality 2027",
        "description": "Future application seed.",
        "theme": "Mortality",
        "page_url": "https://www.who.int/data/mortality-2027",
    }
    monkeypatch.setattr(
        db_schema,
        "DATA_SOURCE_SEEDS",
        [*db_schema.DATA_SOURCE_SEEDS, future_seed],
    )

    await database.init_database()

    source = next(
        source
        for source in await database.list_data_sources()
        if source["source_key"] == "who_mortality_2027"
    )
    assert source["name"] == "User mortality source"
    assert source["page_url"] == "https://example.org/user-mortality"


async def test_upsert_collector_data_source_can_update_seed_key(database):
    await database.init_database()

    updated_source = await database.upsert_collector_data_source(
        "who_gho_indicators",
        "WHO GHO refreshed",
        "Updated by authorized internal sync.",
        "Custom",
        "https://example.org/override",
    )

    assert updated_source["source_key"] == "who_gho_indicators"
    assert updated_source["name"] == "WHO GHO refreshed"

    await database.init_database()

    source = next(
        source
        for source in await database.list_data_sources()
        if source["source_key"] == "who_gho_indicators"
    )
    assert source["name"] == "WHO GHO refreshed"
    assert source["page_url"] == "https://example.org/override"


async def test_create_data_source_rejects_reserved_seed_key_after_normalization(
    database,
):
    await database.init_database()

    with pytest.raises(database.ReservedDataSourceKeyError):
        await database.create_data_source(
            "who_gho_indicators ",
            "User override",
            "Should not be allowed.",
            "Custom",
            "https://example.org/override",
        )

    source = next(
        source
        for source in await database.list_data_sources()
        if source["source_key"] == "who_gho_indicators"
    )
    assert source["name"] == "WHO Global Health Observatory - Indicators"


async def test_upsert_collector_data_source_rejects_invalid_source_key(database):
    await database.init_database()

    with pytest.raises(database.InvalidDataSourceKeyError):
        await database.upsert_collector_data_source(
            "My HDX",
            "Humanitarian Data Exchange",
            "Global datasets.",
            "Humanitarian",
            "https://data.humdata.org/dataset",
        )


async def test_create_data_source_rejects_invalid_page_url_before_pool():
    from app import database

    with pytest.raises(database.InvalidDataSourceURLError):
        await database.create_data_source(
            "my_hdx",
            "Humanitarian Data Exchange",
            "Global datasets.",
            "Humanitarian",
            "not-a-url",
        )


async def test_create_data_source_rejects_duplicate_source_key(database):
    await database.init_database()

    created = await database.create_data_source(
        "my_hdx",
        "Humanitarian Data Exchange",
        "Global datasets.",
        "Humanitarian",
        "https://data.humdata.org/dataset",
    )

    with pytest.raises(database.DuplicateDataSourceKeyError):
        await database.create_data_source(
            "my_hdx",
            "Replacement",
            "Should not overwrite the existing source.",
            "Other",
            "https://example.org/replacement",
        )

    source = await database.get_data_source(int(created["id"]))
    assert source is not None
    assert source["name"] == "Humanitarian Data Exchange"
    assert source["page_url"] == "https://data.humdata.org/dataset"


async def test_business_operations_do_not_apply_schema_migrations(database):
    with pytest.raises(RuntimeError, match="Run init_database"):
        await database.list_data_sources()

    assert await _table_names(database) == set()
    assert await _schema_version(database) == 0


async def test_schema_migration_rechecks_version_after_acquiring_lock(database):
    await database.init_database()

    async def fail_if_called(_connection):
        raise AssertionError("stale migration should not run")

    async with db_connection._require_database_pool().connection() as connection:
        await db_schema._run_schema_migration(connection, 0, 1, fail_if_called)

    assert await _schema_version(database) == db_schema.CURRENT_SCHEMA_VERSION


async def test_save_and_list_collected_datasets(database):
    await database.init_database()

    dataset = _mortality_dataset()
    saved = await database.save_collected_datasets(
        "https://catalog.example.org/",
        [dataset],
    )

    assert len(saved) == 1
    assert saved[0].database_id is not None
    assert saved[0].source_url == "https://catalog.example.org/"

    collected = await database.list_collected_datasets()
    assert len(collected) == 1
    assert collected[0].dataset_url == "https://catalog.example.org/dataset/mortality"
    assert collected[0].geography == ("France",)
    assert collected[0].dataset_signals == {"schema_dataset": True}
    assert collected[0].health_signals == {"matched_keywords": ["mortality"]}
    assert collected[0].distributions[0].format == "CSV"
    assert collected[0].distributions[0].signals == {"ckan_resource": True}
    assert collected[0].validation_results[0].ok is True
    assert collected[0].validation_results[0].size_bytes == 123

    updated_dataset = CollectedDataset(
        dataset_url=dataset.dataset_url,
        title="Updated mortality health dataset",
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform="",
        uploader="",
        geography=("Germany", "France"),
        dataset_probability=0.94,
        dataset_signals=dataset.dataset_signals,
        health_probability=0.85,
        health_label="HEALTH",
        health_signals=dataset.health_signals,
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/mortality.json",
                format="JSON",
                probability=0.95,
                mime_type="application/json",
            )
        ],
        discovery_method="ckan",
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/files/mortality.json",
                final_url="https://catalog.example.org/files/mortality.json",
                format="JSON",
                ok=True,
                http_status=200,
                mime_type="application/json",
            )
        ],
    )

    await database.save_collected_datasets(
        "https://catalog.example.org/",
        [updated_dataset],
    )

    collected = await database.list_collected_datasets()
    assert len(collected) == 1
    assert collected[0].title == "Updated mortality health dataset"
    assert collected[0].geography == ("Germany", "France")
    assert {distribution.format for distribution in collected[0].distributions} == {
        "CSV",
        "JSON",
    }


async def test_save_preserves_every_dataset_discovery_observation(database):
    await database.init_database()

    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/mortality",
        title="Mortality health dataset",
        description="Official mortality health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.92,
        dataset_signals={"schema_dataset": True},
        health_probability=0.8,
        health_label="HEALTH",
        health_signals={"matched_keywords": ["mortality"]},
        distributions=[],
        discovery_method="ckan",
    )

    saved = await database.save_collected_datasets(
        "https://catalog.example.org/",
        [dataset],
    )
    await database.save_collected_datasets("https://catalog.example.org/", [dataset])
    updated_dataset = CollectedDataset(
        dataset_url=dataset.dataset_url,
        title="Mortality health dataset from sitemap",
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform="",
        uploader="",
        dataset_probability=0.9,
        dataset_signals=dataset.dataset_signals,
        health_probability=0.78,
        health_label="HEALTH",
        health_signals=dataset.health_signals,
        distributions=[],
        discovery_method="sitemap",
    )
    await database.save_collected_datasets(
        "https://www.who.int/data/",
        [updated_dataset],
    )

    collected = (await database.list_collected_datasets())[0]
    observations = await database.list_dataset_discovery_observations(
        saved[0].database_id
    )

    assert collected.source_url == "https://www.who.int/data/"
    assert collected.discovery_method == "sitemap"
    observation_keys = [
        (
            observation["source_url"],
            observation["discovery_method"],
            observation["collection_job_id"],
        )
        for observation in observations
    ]
    assert len(observations) == 3
    assert observation_keys.count(("https://catalog.example.org/", "ckan", None)) == 2
    assert observation_keys.count(("https://www.who.int/data/", "sitemap", None)) == 1
    assert all(observation["observed_at"] for observation in observations)


async def test_save_links_dataset_discovery_observation_to_collection_job(database):
    await database.init_database()
    job = await database.create_collection_job("https://catalog.example.org/")
    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/mortality",
        title="Mortality health dataset",
        description="Official mortality health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.92,
        dataset_signals={"schema_dataset": True},
        health_probability=0.8,
        health_label="HEALTH",
        health_signals={"matched_keywords": ["mortality"]},
        distributions=[],
        discovery_method="ckan",
    )

    saved = await database.save_collected_datasets(
        "https://catalog.example.org/",
        [dataset],
        collection_job_id=int(job["id"]),
    )

    observations = await database.list_dataset_discovery_observations(
        saved[0].database_id
    )

    assert len(observations) == 1
    assert observations[0]["collection_job_id"] == job["id"]
    assert observations[0]["source_url"] == "https://catalog.example.org/"
    assert observations[0]["discovery_method"] == "ckan"


async def test_distribution_upsert_preserves_unseen_rows_and_seen_timestamps(database):
    await database.init_database()

    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/upsert",
        title="Upsert health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/current.csv",
                format="CSV",
                probability=0.9,
            ),
            DistributionCandidate(
                url="https://catalog.example.org/files/stale.csv",
                format="CSV",
                probability=0.7,
            ),
        ],
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/files/current.csv",
                final_url="https://catalog.example.org/files/current.csv",
                format="CSV",
                ok=True,
                http_status=200,
                mime_type="text/csv",
            )
        ],
    )
    await database.save_collected_datasets("https://catalog.example.org/", [dataset])

    await _execute(
        database,
        """
        UPDATE collected_datasets
        SET first_seen_at = TIMESTAMPTZ '2000-01-01 00:00:00+00',
            last_seen_at = TIMESTAMPTZ '2000-01-01 00:00:00+00'
        WHERE dataset_url = %s
        """,
        (dataset.dataset_url,),
    )
    await _execute(
        database,
        """
        UPDATE collected_distributions
        SET first_seen_at = TIMESTAMPTZ '2000-01-01 00:00:00+00',
            last_seen_at = TIMESTAMPTZ '2000-01-01 00:00:00+00',
            last_checked_at = TIMESTAMPTZ '2000-01-01 00:00:00+00'
        WHERE url = %s
        """,
        ("https://catalog.example.org/files/current.csv",),
    )
    await _execute(
        database,
        """
        UPDATE collected_distributions
        SET first_seen_at = TIMESTAMPTZ '2001-01-01 00:00:00+00',
            last_seen_at = TIMESTAMPTZ '2001-01-01 00:00:00+00',
            last_checked_at = NULL
        WHERE url = %s
        """,
        ("https://catalog.example.org/files/stale.csv",),
    )

    updated_dataset = CollectedDataset(
        dataset_url=dataset.dataset_url,
        title="Upsert health dataset updated",
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform="",
        uploader="",
        dataset_probability=0.85,
        dataset_signals={},
        health_probability=0.75,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/current.csv",
                format="CSV",
                probability=0.95,
            )
        ],
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/files/current.csv",
                final_url="https://catalog.example.org/files/current.csv",
                format="CSV",
                ok=True,
                http_status=204,
                mime_type="text/csv",
            )
        ],
    )
    await database.save_collected_datasets(
        "https://catalog.example.org/",
        [updated_dataset],
    )

    collected = (await database.list_collected_datasets())[0]
    distributions_by_url = {
        distribution.url: distribution for distribution in collected.distributions
    }

    assert collected.first_seen_at.startswith("2000-01-01T00:00:00")
    assert not collected.last_seen_at.startswith("2000-01-01T00:00:00")
    assert set(distributions_by_url) == {
        "https://catalog.example.org/files/current.csv",
        "https://catalog.example.org/files/stale.csv",
    }
    current_distribution = distributions_by_url[
        "https://catalog.example.org/files/current.csv"
    ]
    stale_distribution = distributions_by_url[
        "https://catalog.example.org/files/stale.csv"
    ]
    assert current_distribution.probability == 0.95
    assert current_distribution.first_seen_at.startswith("2000-01-01T00:00:00")
    assert not current_distribution.last_seen_at.startswith("2000-01-01T00:00:00")
    assert not current_distribution.last_checked_at.startswith("2000-01-01T00:00:00")
    assert stale_distribution.first_seen_at.startswith("2001-01-01T00:00:00")
    assert stale_distribution.last_seen_at.startswith("2001-01-01T00:00:00")
    assert stale_distribution.last_checked_at == ""

    validation_by_url = {
        validation.url: validation for validation in collected.validation_results
    }
    assert (
        validation_by_url["https://catalog.example.org/files/current.csv"].http_status
        == 204
    )

    checked_after_validation = current_distribution.last_checked_at
    unchecked_dataset = CollectedDataset(
        dataset_url=dataset.dataset_url,
        title="Upsert health dataset checked earlier",
        description=dataset.description,
        publisher=dataset.publisher,
        hosting_platform="",
        uploader="",
        dataset_probability=0.86,
        dataset_signals={},
        health_probability=0.76,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/current.csv",
                format="CSV",
                probability=0.99,
            )
        ],
        validation_results=[],
    )
    await database.save_collected_datasets(
        "https://catalog.example.org/",
        [unchecked_dataset],
    )

    collected = (await database.list_collected_datasets())[0]
    current_distribution = next(
        distribution
        for distribution in collected.distributions
        if distribution.url == "https://catalog.example.org/files/current.csv"
    )
    validation = next(
        validation
        for validation in collected.validation_results
        if validation.url == "https://catalog.example.org/files/current.csv"
    )
    assert current_distribution.probability == 0.99
    assert current_distribution.last_checked_at == checked_after_validation
    assert validation.http_status == 204


async def test_validation_results_match_distribution_by_url_and_format(database):
    await database.init_database()

    shared_url = "https://catalog.example.org/files/shared"
    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/shared-formats",
        title="Shared URL health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(url=shared_url, format="CSV", probability=0.9),
            DistributionCandidate(url=shared_url, format="JSON", probability=0.8),
        ],
        validation_results=[
            ValidationResult(
                url=shared_url,
                final_url=f"{shared_url}?format=csv",
                format="CSV",
                ok=True,
                http_status=201,
            ),
            ValidationResult(
                url=shared_url,
                final_url=f"{shared_url}?format=json",
                format="JSON",
                ok=True,
                http_status=202,
            ),
        ],
    )

    await database.save_collected_datasets("https://catalog.example.org/", [dataset])

    validation_by_format = {
        validation.format: validation
        for validation in (await database.list_collected_datasets())[0].validation_results
    }
    assert validation_by_format["CSV"].http_status == 201
    assert validation_by_format["CSV"].final_url == f"{shared_url}?format=csv"
    assert validation_by_format["JSON"].http_status == 202
    assert validation_by_format["JSON"].final_url == f"{shared_url}?format=json"


async def test_duplicate_validation_results_fail_clearly(database):
    await database.init_database()

    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/duplicate-validation",
        title="Duplicate validation health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/duplicate.csv",
                format="CSV",
                probability=0.9,
            )
        ],
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/files/duplicate.csv",
                final_url="https://catalog.example.org/files/duplicate.csv",
                format="CSV",
                ok=True,
                http_status=200,
            ),
            ValidationResult(
                url="https://catalog.example.org/files/duplicate.csv",
                final_url="https://catalog.example.org/files/duplicate.csv",
                format="CSV",
                ok=True,
                http_status=204,
            ),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate validation result"):
        await database.save_collected_datasets("https://catalog.example.org/", [dataset])

    assert await database.list_collected_datasets() == []


async def test_orphan_validation_result_fails_clearly(database):
    await database.init_database()

    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/orphan-validation",
        title="Orphan validation health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/current.csv",
                format="CSV",
                probability=0.9,
            )
        ],
        validation_results=[
            ValidationResult(
                url="https://catalog.example.org/files/orphan.csv",
                final_url="https://catalog.example.org/files/orphan.csv",
                format="CSV",
                ok=True,
                http_status=200,
            )
        ],
    )

    with pytest.raises(ValueError, match="does not match any distribution"):
        await database.save_collected_datasets("https://catalog.example.org/", [dataset])

    assert await database.list_collected_datasets() == []


async def test_save_collected_distribution_without_validation_result(database):
    await database.init_database()

    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/unvalidated",
        title="Unvalidated health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/unvalidated.csv",
                format="CSV",
                probability=0.9,
            )
        ],
        validation_results=[],
    )

    await database.save_collected_datasets("https://catalog.example.org/", [dataset])

    collected = await database.list_collected_datasets()
    assert len(collected) == 1
    assert [distribution.url for distribution in collected[0].distributions] == [
        "https://catalog.example.org/files/unvalidated.csv"
    ]
    assert collected[0].validation_results == []


async def test_signal_json_errors_are_explicit():
    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON in stored signals field collected_datasets.dataset_signals",
    ):
        db_serialization._deserialize_signals(
            "{malformed",
            "collected_datasets.dataset_signals",
        )

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON type in stored signals field collected_datasets.dataset_signals",
    ):
        db_serialization._deserialize_signals(
            [],
            "collected_datasets.dataset_signals",
        )


async def test_corrupted_stored_signals_fail_when_listing_datasets(database):
    await database.init_database()
    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/corrupted-signals",
        title="Corrupted signals health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[],
    )
    await database.save_collected_datasets("https://catalog.example.org/", [dataset])
    await _execute(
        database,
        """
        UPDATE collected_datasets
        SET dataset_signals = '[]'::jsonb
        WHERE dataset_url = %s
        """,
        (dataset.dataset_url,),
    )

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="collected_datasets.dataset_signals",
    ):
        await database.list_collected_datasets()


async def test_discovery_methods_json_errors_are_explicit():
    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON in stored discovery methods field",
    ):
        db_serialization._deserialize_discovery_methods("{malformed")

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON type in stored discovery methods field",
    ):
        db_serialization._deserialize_discovery_methods('"bonjour"')

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON items in stored discovery methods field",
    ):
        db_serialization._deserialize_discovery_methods(["google", 42, "bing"])

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="expected list, got dict",
    ):
        db_serialization._deserialize_discovery_methods({"method": "api"})

    assert db_serialization._deserialize_discovery_methods(["google", "bing"]) == [
        "google",
        "bing",
    ]

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid discovery method items before storage",
    ):
        db_serialization._serialize_discovery_methods(("google", 42, "bing"))

    assert db_serialization._deserialize_geography(
        [" France ", "Germany", "France"]
    ) == ["France", "Germany"]

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON type in stored geography field",
    ):
        db_serialization._deserialize_geography({"country": "France"})

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid JSON items in stored geography field",
    ):
        db_serialization._deserialize_geography(["France", 42])

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid geography items before storage",
    ):
        db_serialization._serialize_geography(("France", " "))

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid signal keys before storage",
    ):
        db_serialization._serialize_signals({1: "score"})

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid signals before storage",
    ):
        db_serialization._serialize_signals([])

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Value is not JSON serializable for storage",
    ):
        db_serialization._serialize_signals({"bad": object()})

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Invalid signal keys before storage",
    ):
        db_serialization._serialize_signals({"nested": {1: "score"}})

    with pytest.raises(
        db_serialization.StoredJSONError,
        match="Value is not JSON serializable for storage",
    ):
        db_serialization._serialize_signals({"bad": float("nan")})


async def test_timestamp_formatting_errors_are_explicit():
    assert (
        db_serialization._format_timestamp(
            datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
        )
        == "2026-08-25T12:30:00+00:00"
    )
    assert db_serialization._format_optional_timestamp(None) == ""

    with pytest.raises(
        db_serialization.StoredTimestampError,
        match="expected datetime, got str",
    ):
        db_serialization._format_timestamp("2026-08-25T12:30:00+00:00")

    with pytest.raises(
        db_serialization.StoredTimestampError,
        match="expected timezone-aware datetime",
    ):
        db_serialization._format_timestamp(datetime(2026, 8, 25, 12, 30))


async def test_non_json_serializable_signals_do_not_leave_partial_rows(database):
    await database.init_database()
    dataset = CollectedDataset(
        dataset_url="https://catalog.example.org/dataset/bad-signals",
        title="Bad signals health dataset",
        description="Official health data.",
        publisher="National Health Agency",
        hosting_platform="",
        uploader="",
        dataset_probability=0.8,
        dataset_signals={},
        health_probability=0.7,
        health_label="HEALTH",
        health_signals={},
        distributions=[
            DistributionCandidate(
                url="https://catalog.example.org/files/bad-signals.csv",
                format="CSV",
                probability=0.9,
                signals={"bad": object()},
            )
        ],
    )

    with pytest.raises(db_serialization.StoredJSONError):
        await database.save_collected_datasets("https://catalog.example.org/", [dataset])

    assert await database.list_collected_datasets() == []
    assert await database.list_dataset_discovery_observations() == []


async def test_collection_job_lifecycle(database):
    await database.init_database()

    job = await database.create_collection_job("https://catalog.example.org/")

    assert job["id"] == 1
    assert job["source_url"] == "https://catalog.example.org/"
    assert job["status"] == "pending"
    assert job["saved_count"] == 0
    assert job["discovered_count"] == 0
    assert job["discovery_methods"] == []
    assert job["message"] == "Collecte en attente."

    running = await database.mark_collection_job_running(int(job["id"]))
    assert running["status"] == "running"
    assert running["message"] == "Collecte en cours."

    done = await database.mark_collection_job_done(
        int(job["id"]),
        3,
        CollectionReport(
            discovered_count=20,
            analyzed_count=5,
            accepted_count=3,
            rejected_count=2,
            invalid_distribution_count=1,
            discovery_methods=("ckan", "sitemap"),
        ),
    )
    assert done["status"] == "done"
    assert done["saved_count"] == 3
    assert done["discovered_count"] == 20
    assert done["analyzed_count"] == 5
    assert done["accepted_count"] == 3
    assert done["rejected_count"] == 2
    assert done["invalid_distribution_count"] == 1
    assert done["discovery_methods"] == ["ckan", "sitemap"]
    assert done["message"] == "3 dataset(s) sauvegardé(s)."
    assert done["finished_at"] != ""

    fetched = await database.get_collection_job(int(job["id"]))
    assert fetched == done


async def test_collection_job_status_transitions_are_guarded(database):
    await database.init_database()

    job = await database.create_collection_job("https://catalog.example.org/")
    job_id = int(job["id"])

    assert await database.mark_collection_job_done(job_id, 1) is None
    assert (await database.get_collection_job(job_id))["status"] == "pending"

    running = await database.mark_collection_job_running(job_id)
    assert running["status"] == "running"

    done = await database.mark_collection_job_done(job_id, 1)
    assert done["status"] == "done"

    assert await database.mark_collection_job_running(job_id) is None
    assert await database.mark_collection_job_error(job_id, "late failure") is None
    assert (await database.get_collection_job(job_id))["status"] == "done"

    failed_job = await database.create_collection_job("https://catalog.example.org/fail")
    failed_job_id = int(failed_job["id"])

    failed = await database.mark_collection_job_error(failed_job_id, "startup failure")
    assert failed["status"] == "error"

    assert await database.mark_collection_job_running(failed_job_id) is None
    assert await database.mark_collection_job_done(failed_job_id, 1) is None
    assert (await database.get_collection_job(failed_job_id))["status"] == "error"


async def test_collection_job_records_errors(database):
    await database.init_database()

    job = await database.create_collection_job("https://catalog.example.org/")
    failed = await database.mark_collection_job_error(int(job["id"]), "network timeout")

    assert failed["status"] == "error"
    assert failed["message"] == "Collecte échouée."
    assert failed["error"] == "network timeout"
    assert failed["finished_at"] != ""
