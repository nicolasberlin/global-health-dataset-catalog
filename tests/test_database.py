from __future__ import annotations

import importlib

from collector.storage.models import CollectedDataset, DistributionCandidate, ValidationResult


def test_init_database_seeds_dataset_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("GLOBAL_HEALTH_DB_PATH", str(tmp_path / "catalog.db"))

    from app import database

    importlib.reload(database)
    database.init_database()

    sources = database.list_data_sources()
    assert len(sources) == 2
    assert {source["source_key"] for source in sources} == {
        "who_gho_indicators",
        "who_gho_life_expectancy",
    }
    assert all(source["page_url"].startswith("https://www.who.int/") for source in sources)
    assert {source["theme"] for source in sources} == {"General", "Mortality"}

    database.upsert_data_source(
        "who_gho_life_expectancy",
        "Updated life expectancy",
        "Updated description",
        "Mortality",
        "https://www.who.int/data/gho/data/indicators/",
    )
    sources = database.list_data_sources()
    assert len(sources) == 2
    assert any(source["name"] == "Updated life expectancy" for source in sources)

    with database.get_connection() as connection:
        table_names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(data_sources)").fetchall()
        }

    assert "accounts" not in table_names
    assert columns == {"id", "source_key", "name", "description", "theme", "page_url"}


def test_init_database_deduplicates_legacy_seed_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("GLOBAL_HEALTH_DB_PATH", str(tmp_path / "legacy.db"))

    from app import database

    importlib.reload(database)

    with database.get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                theme TEXT NOT NULL DEFAULT 'General',
                page_url TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO data_sources (name, description, theme, page_url)
            VALUES (?, ?, ?, ?)
            """,
            (
                "WHO Global Health Observatory - Life expectancy",
                "Old description",
                "General",
                "https://old.example.test",
            ),
        )

    database.init_database()

    sources = database.list_data_sources()
    life_expectancy_sources = [
        source
        for source in sources
        if source["name"] == "WHO Global Health Observatory - Life expectancy"
    ]

    assert len(life_expectancy_sources) == 1
    assert life_expectancy_sources[0]["source_key"] == "who_gho_life_expectancy"
    assert life_expectancy_sources[0]["theme"] == "Mortality"


def test_save_and_list_collected_datasets(tmp_path, monkeypatch):
    monkeypatch.setenv("GLOBAL_HEALTH_DB_PATH", str(tmp_path / "collected.db"))

    from app import database

    importlib.reload(database)
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
    assert [distribution.format for distribution in collected[0].distributions] == ["JSON"]
