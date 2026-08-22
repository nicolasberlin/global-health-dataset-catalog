from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException


def test_create_source_rejects_reserved_seed_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GLOBAL_HEALTH_DB_PATH", str(tmp_path / "sources.db"))

    from app import database
    from app.routes import sources

    importlib.reload(database)
    importlib.reload(sources)
    database.init_database()

    with pytest.raises(HTTPException) as exception_info:
        sources.create_source(
            sources.DataSourceCreate(
                source_key="who_gho_indicators",
                name="User override",
                description="Should not be allowed.",
                theme="Custom",
                page_url="https://example.org/override",
            )
        )

    assert exception_info.value.status_code == 400
    assert "reserved by the application" in str(exception_info.value.detail)
