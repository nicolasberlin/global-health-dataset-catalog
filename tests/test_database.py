from __future__ import annotations

import importlib


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
