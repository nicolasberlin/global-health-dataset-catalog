from __future__ import annotations

import importlib
import logging
import sqlite3

import pytest

from collector.storage.models import (
    CollectedDataset,
    CollectionReport,
    DistributionCandidate,
    ValidationResult,
)

SCHEMA_TABLES = (
    "data_sources",
    "collected_datasets",
    "collected_distributions",
    "dataset_discovery_observations",
    "collection_jobs",
)


def _load_database(monkeypatch, tmp_path, filename: str):
    monkeypatch.setenv("GLOBAL_HEALTH_DB_PATH", str(tmp_path / filename))

    from app import database

    return importlib.reload(database)


def _user_version(database) -> int:
    with database.get_connection() as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _table_names(database) -> set[str]:
    with database.get_connection() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row["name"] for row in rows}


def _assert_schema_constraints_are_enforced(database, suffix: str = "") -> None:
    with database.get_connection() as connection:
        dataset_id = connection.execute(
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"https://catalog.example.org/dataset/valid{suffix}",
                "Valid dataset",
                0.8,
                0.7,
                "HEALTH",
            ),
        ).lastrowid

        invalid_statements = [
            (
                """
                INSERT INTO data_sources (
                    source_key, name, description, theme, page_url
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                ("", "Empty source key", "", "General", "https://example.org/"),
            ),
            (
                """
                INSERT INTO data_sources (
                    source_key, name, description, theme, page_url
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                ("empty_page_url", "Empty page URL", "", "General", ""),
            ),
            (
                """
                INSERT INTO collected_datasets (
                    dataset_url, title, dataset_probability, health_probability,
                    health_label
                )
                VALUES (?, ?, ?, ?, ?)
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
                VALUES (?, ?, ?, ?, ?)
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
                    dataset_id, url, format, probability, same_domain
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    f"https://catalog.example.org/files/bad-domain{suffix}.csv",
                    "CSV",
                    0.9,
                    -5,
                ),
            ),
            (
                """
                INSERT INTO collected_distributions (
                    dataset_id, url, format, probability, validation_ok
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    f"https://catalog.example.org/files/bad-validation{suffix}.csv",
                    "CSV",
                    0.9,
                    784,
                ),
            ),
            (
                """
                INSERT INTO collection_jobs (source_url)
                VALUES (?)
                """,
                ("",),
            ),
            (
                """
                INSERT INTO collection_jobs (source_url, status)
                VALUES (?, ?)
                """,
                (f"https://catalog.example.org/bad-status{suffix}", "banana"),
            ),
            (
                """
                INSERT INTO collection_jobs (source_url, saved_count)
                VALUES (?, ?)
                """,
                (f"https://catalog.example.org/bad-saved-count{suffix}", -1),
            ),
            (
                """
                INSERT INTO collection_jobs (source_url, discovered_count)
                VALUES (?, ?)
                """,
                (f"https://catalog.example.org/bad-discovered-count{suffix}", -1),
            ),
        ]

        for sql, parameters in invalid_statements:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql, parameters)


def test_init_database_seeds_dataset_pages(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "catalog.db")

    database.init_database()

    sources = database.list_data_sources()
    assert len(sources) == 2
    assert {source["source_key"] for source in sources} == {
        "who_gho_indicators",
        "who_gho_life_expectancy",
    }
    assert all(source["page_url"].startswith("https://www.who.int/") for source in sources)
    assert {source["theme"] for source in sources} == {"General", "Mortality"}
    assert _user_version(database) == database.CURRENT_SCHEMA_VERSION

    database.upsert_data_source(
        "user_defined_source",
        "User source",
        "User description",
        "Custom",
        "https://example.org/user-source",
    )
    database.init_database()

    sources = database.list_data_sources()
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


def test_init_database_creates_current_schema_with_integrity(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "integrity.db")

    database.init_database()

    with database.get_connection() as connection:
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert _user_version(database) == database.CURRENT_SCHEMA_VERSION
    assert set(SCHEMA_TABLES).issubset(_table_names(database))
    assert foreign_key_violations == []
    _assert_schema_constraints_are_enforced(database, "-fresh")


def test_seen_timestamps_default_to_current_timestamp(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "timestamp-defaults.db")
    database.init_database()

    with database.get_connection() as connection:
        dataset_id = connection.execute(
            """
            INSERT INTO collected_datasets (
                dataset_url, title, dataset_probability, health_probability,
                health_label
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "https://catalog.example.org/dataset/default-timestamps",
                "Dataset with default timestamps",
                0.8,
                0.7,
                "HEALTH",
            ),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO collected_distributions (
                dataset_id, url, format, probability
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                dataset_id,
                "https://catalog.example.org/files/default-timestamps.csv",
                "CSV",
                0.9,
            ),
        )
        dataset_row = connection.execute(
            """
            SELECT first_seen_at, last_seen_at
            FROM collected_datasets
            WHERE id = ?
            """,
            (dataset_id,),
        ).fetchone()
        distribution_row = connection.execute(
            """
            SELECT first_seen_at, last_seen_at, last_checked_at
            FROM collected_distributions
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchone()

    assert dataset_row["first_seen_at"] != ""
    assert dataset_row["last_seen_at"] != ""
    assert distribution_row["first_seen_at"] != ""
    assert distribution_row["last_seen_at"] != ""
    assert distribution_row["last_checked_at"] == ""


def test_init_database_preserves_unrelated_accounts_table(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "catalog-with-accounts.db")

    with database.get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO accounts (email) VALUES (?)",
            ("admin@example.org",),
        )

    database.init_database()

    with database.get_connection() as connection:
        account_rows = connection.execute("SELECT email FROM accounts").fetchall()

    assert [row["email"] for row in account_rows] == ["admin@example.org"]
    assert set(SCHEMA_TABLES).issubset(_table_names(database))


def test_init_database_rejects_unversioned_managed_tables_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database = _load_database(monkeypatch, tmp_path, "unversioned-managed.db")

    with database.get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
            """
        )
        connection.execute("INSERT INTO data_sources (name) VALUES (?)", ("Legacy",))

    with pytest.raises(RuntimeError, match="Unversioned database already contains"):
        database.init_database()

    with database.get_connection() as connection:
        rows = connection.execute("SELECT name FROM data_sources").fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert [row["name"] for row in rows] == ["Legacy"]
    assert "collected_datasets" not in _table_names(database)
    assert version == 0


def test_init_database_rejects_current_reserved_source_key_collision_before_seed(
    tmp_path,
    monkeypatch,
):
    database = _load_database(monkeypatch, tmp_path, "reserved-current.db")

    with database.get_connection() as connection:
        for schema in database.INITIAL_SCHEMA_STATEMENTS:
            connection.execute(schema)
        connection.execute(
            """
            INSERT INTO data_sources (source_key, name, description, theme, page_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "who_gho_life_expectancy",
                "Custom life expectancy source",
                "Already at current schema.",
                "Custom",
                "https://example.org/current-collision",
            ),
        )
        connection.execute(f"PRAGMA user_version = {database.CURRENT_SCHEMA_VERSION}")

    with pytest.raises(RuntimeError, match="Cannot safely seed data_sources"):
        database.init_database()

    with database.get_connection() as connection:
        row = connection.execute(
            """
            SELECT name, page_url
            FROM data_sources
            WHERE source_key = ?
            """,
            ("who_gho_life_expectancy",),
        ).fetchone()

    assert row["name"] == "Custom life expectancy source"
    assert row["page_url"] == "https://example.org/current-collision"


def test_future_seed_collision_fails_before_overwrite(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "future-seed.db")
    database.init_database()
    database.upsert_data_source(
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
        database,
        "DATA_SOURCE_SEEDS",
        [*database.DATA_SOURCE_SEEDS, future_seed],
    )

    with pytest.raises(RuntimeError, match="Cannot safely seed data_sources"):
        database.init_database()

    source = next(
        source
        for source in database.list_data_sources()
        if source["source_key"] == "who_mortality_2027"
    )
    assert source["name"] == "User mortality source"
    assert source["page_url"] == "https://example.org/user-mortality"


def test_upsert_data_source_rejects_reserved_seed_key(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "reserved-key.db")
    database.init_database()

    with pytest.raises(database.ReservedDataSourceKeyError):
        database.upsert_data_source(
            "who_gho_indicators",
            "User override",
            "Should not be allowed.",
            "Custom",
            "https://example.org/override",
        )

    source = next(
        source
        for source in database.list_data_sources()
        if source["source_key"] == "who_gho_indicators"
    )
    assert source["name"] == "WHO Global Health Observatory - Indicators"


def test_business_operations_do_not_apply_schema_migrations(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "business-before-init.db")

    with pytest.raises(RuntimeError, match="Run init_database"):
        database.list_data_sources()

    assert _table_names(database) == set()
    assert _user_version(database) == 0


def test_schema_migration_rechecks_version_after_acquiring_lock(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "stale-lock.db")
    database.init_database()

    def fail_if_called(_connection):
        raise AssertionError("stale migration should not run")

    with database.get_connection() as connection:
        database._run_schema_migration(connection, 0, 1, fail_if_called)

    assert _user_version(database) == database.CURRENT_SCHEMA_VERSION


def test_save_and_list_collected_datasets(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "collected.db")
    database.init_database()

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

    saved = database.save_collected_datasets("https://catalog.example.org/", [dataset])

    assert len(saved) == 1
    assert saved[0].database_id is not None
    assert saved[0].source_url == "https://catalog.example.org/"

    collected = database.list_collected_datasets()
    assert len(collected) == 1
    assert collected[0].dataset_url == "https://catalog.example.org/dataset/mortality"
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

    database.save_collected_datasets("https://catalog.example.org/", [updated_dataset])

    collected = database.list_collected_datasets()
    assert len(collected) == 1
    assert collected[0].title == "Updated mortality health dataset"
    assert {distribution.format for distribution in collected[0].distributions} == {
        "CSV",
        "JSON",
    }


def test_save_preserves_every_dataset_discovery_observation(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "discovery-observations.db")
    database.init_database()

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

    saved = database.save_collected_datasets("https://catalog.example.org/", [dataset])
    database.save_collected_datasets("https://catalog.example.org/", [dataset])
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
    database.save_collected_datasets("https://www.who.int/data/", [updated_dataset])

    collected = database.list_collected_datasets()[0]
    observations = database.list_dataset_discovery_observations(saved[0].database_id)

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


def test_save_links_dataset_discovery_observation_to_collection_job(
    tmp_path,
    monkeypatch,
):
    database = _load_database(monkeypatch, tmp_path, "job-discovery-observations.db")
    database.init_database()
    job = database.create_collection_job("https://catalog.example.org/")
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

    saved = database.save_collected_datasets(
        "https://catalog.example.org/",
        [dataset],
        collection_job_id=int(job["id"]),
    )

    observations = database.list_dataset_discovery_observations(saved[0].database_id)

    assert len(observations) == 1
    assert observations[0]["collection_job_id"] == job["id"]
    assert observations[0]["source_url"] == "https://catalog.example.org/"
    assert observations[0]["discovery_method"] == "ckan"


def test_distribution_upsert_preserves_unseen_rows_and_seen_timestamps(
    tmp_path,
    monkeypatch,
):
    database = _load_database(monkeypatch, tmp_path, "distribution-upsert.db")
    database.init_database()

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
    database.save_collected_datasets("https://catalog.example.org/", [dataset])

    with database.get_connection() as connection:
        connection.execute(
            """
            UPDATE collected_datasets
            SET first_seen_at = '2000-01-01 00:00:00',
                last_seen_at = '2000-01-01 00:00:00'
            WHERE dataset_url = ?
            """,
            (dataset.dataset_url,),
        )
        connection.execute(
            """
            UPDATE collected_distributions
            SET first_seen_at = '2000-01-01 00:00:00',
                last_seen_at = '2000-01-01 00:00:00',
                last_checked_at = '2000-01-01 00:00:00'
            WHERE url = ?
            """,
            ("https://catalog.example.org/files/current.csv",),
        )
        connection.execute(
            """
            UPDATE collected_distributions
            SET first_seen_at = '2001-01-01 00:00:00',
                last_seen_at = '2001-01-01 00:00:00',
                last_checked_at = ''
            WHERE url = ?
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
    database.save_collected_datasets("https://catalog.example.org/", [updated_dataset])

    collected = database.list_collected_datasets()[0]
    distributions_by_url = {
        distribution.url: distribution
        for distribution in collected.distributions
    }

    assert collected.first_seen_at == "2000-01-01 00:00:00"
    assert collected.last_seen_at != "2000-01-01 00:00:00"
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
    assert current_distribution.first_seen_at == "2000-01-01 00:00:00"
    assert current_distribution.last_seen_at != "2000-01-01 00:00:00"
    assert current_distribution.last_checked_at != "2000-01-01 00:00:00"
    assert stale_distribution.first_seen_at == "2001-01-01 00:00:00"
    assert stale_distribution.last_seen_at == "2001-01-01 00:00:00"

    validation_by_url = {
        validation.url: validation
        for validation in collected.validation_results
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
    database.save_collected_datasets("https://catalog.example.org/", [unchecked_dataset])

    collected = database.list_collected_datasets()[0]
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


def test_validation_results_match_distribution_by_url_and_format(
    tmp_path,
    monkeypatch,
):
    database = _load_database(monkeypatch, tmp_path, "validation-key.db")
    database.init_database()

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

    database.save_collected_datasets("https://catalog.example.org/", [dataset])

    validation_by_format = {
        validation.format: validation
        for validation in database.list_collected_datasets()[0].validation_results
    }
    assert validation_by_format["CSV"].http_status == 201
    assert validation_by_format["CSV"].final_url == f"{shared_url}?format=csv"
    assert validation_by_format["JSON"].http_status == 202
    assert validation_by_format["JSON"].final_url == f"{shared_url}?format=json"


def test_duplicate_validation_results_fail_clearly(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "duplicate-validation.db")
    database.init_database()

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
        database.save_collected_datasets("https://catalog.example.org/", [dataset])

    assert database.list_collected_datasets() == []


def test_save_collected_distribution_without_validation_result(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "unvalidated.db")
    database.init_database()

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

    database.save_collected_datasets("https://catalog.example.org/", [dataset])

    collected = database.list_collected_datasets()

    assert len(collected) == 1
    assert [distribution.url for distribution in collected[0].distributions] == [
        "https://catalog.example.org/files/unvalidated.csv"
    ]
    assert collected[0].validation_results == []


def test_new_collected_schema_rejects_invalid_values(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "constraints.db")
    database.init_database()

    with database.get_connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO collected_datasets (
                    dataset_url, title, dataset_probability, health_probability,
                    health_label
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "https://catalog.example.org/dataset/bad-probability",
                    "Bad probability",
                    16.42,
                    0.7,
                    "HEALTH",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO collection_jobs (source_url, status)
                VALUES (?, ?)
                """,
                ("https://catalog.example.org/", "banana"),
            )


def test_signal_json_errors_are_explicit(monkeypatch, tmp_path):
    database = _load_database(monkeypatch, tmp_path, "json-errors.db")

    with pytest.raises(
        database.StoredJSONError,
        match="Invalid JSON in stored signals field collected_datasets.dataset_signals",
    ):
        database._deserialize_signals(
            "{malformed",
            "collected_datasets.dataset_signals",
        )

    with pytest.raises(
        database.StoredJSONError,
        match="Invalid JSON type in stored signals field collected_datasets.dataset_signals",
    ):
        database._deserialize_signals(
            "[]",
            "collected_datasets.dataset_signals",
        )


def test_corrupted_stored_signals_fail_when_listing_datasets(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "corrupted-signals.db")
    database.init_database()
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
    database.save_collected_datasets("https://catalog.example.org/", [dataset])
    with database.get_connection() as connection:
        connection.execute(
            """
            UPDATE collected_datasets
            SET dataset_signals = ?
            WHERE dataset_url = ?
            """,
            ("{malformed", dataset.dataset_url),
        )

    with pytest.raises(
        database.StoredJSONError,
        match="collected_datasets.dataset_signals",
    ):
        database.list_collected_datasets()


def test_discovery_methods_json_errors_are_visible(monkeypatch, tmp_path, caplog):
    database = _load_database(monkeypatch, tmp_path, "discovery-method-json-errors.db")

    with caplog.at_level(logging.WARNING, logger="app.database"):
        assert database._deserialize_discovery_methods('"bonjour"') == []
        assert database._deserialize_discovery_methods('["google", 42, "bing"]') == [
            "google",
            "bing",
        ]

    assert "Invalid discovery methods JSON type" in caplog.text
    assert "Invalid discovery methods JSON items ignored at indexes: [1]" in caplog.text

    with pytest.raises(TypeError):
        database._serialize_signals({"bad": object()})


def test_non_json_serializable_signals_do_not_leave_partial_rows(
    tmp_path,
    monkeypatch,
):
    database = _load_database(monkeypatch, tmp_path, "bad-signals-write.db")
    database.init_database()
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

    with pytest.raises(TypeError):
        database.save_collected_datasets("https://catalog.example.org/", [dataset])

    assert database.list_collected_datasets() == []
    assert database.list_dataset_discovery_observations() == []


def test_collection_job_lifecycle(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "jobs.db")
    database.init_database()

    job = database.create_collection_job("https://catalog.example.org/")

    assert job["id"] == 1
    assert job["source_url"] == "https://catalog.example.org/"
    assert job["status"] == "pending"
    assert job["saved_count"] == 0
    assert job["discovered_count"] == 0
    assert job["discovery_methods"] == []
    assert job["message"] == "Collecte en attente."

    running = database.mark_collection_job_running(int(job["id"]))
    assert running["status"] == "running"
    assert running["message"] == "Collecte en cours."

    done = database.mark_collection_job_done(
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

    fetched = database.get_collection_job(int(job["id"]))
    assert fetched == done


def test_collection_job_records_errors(tmp_path, monkeypatch):
    database = _load_database(monkeypatch, tmp_path, "job-error.db")
    database.init_database()

    job = database.create_collection_job("https://catalog.example.org/")
    failed = database.mark_collection_job_error(int(job["id"]), "network timeout")

    assert failed["status"] == "error"
    assert failed["message"] == "Collecte échouée."
    assert failed["error"] == "network timeout"
    assert failed["finished_at"] != ""
