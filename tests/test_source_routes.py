from __future__ import annotations

import importlib

import pytest
from app.security import APIPrincipal
from fastapi import HTTPException
from pydantic import ValidationError

pytestmark = pytest.mark.anyio
PRINCIPAL = APIPrincipal(owner_id="test-user")


def _allow_source_creation(sources, monkeypatch) -> None:
    async def allow_request(principal, operation):
        assert principal == PRINCIPAL
        assert operation == "source_creation"

    monkeypatch.setattr(sources, "enforce_api_quota", allow_request)


async def test_create_source_normalizes_text_fields(monkeypatch):
    from app.routes import sources

    importlib.reload(sources)
    _allow_source_creation(sources, monkeypatch)
    captured_arguments = {}

    async def fake_create_data_source(
        source_key: str,
        name: str,
        description: str,
        theme: str,
        page_url: str,
    ):
        captured_arguments.update(
            {
                "source_key": source_key,
                "name": name,
                "description": description,
                "theme": theme,
                "page_url": page_url,
            }
        )
        return {
            "id": 42,
            "source_key": source_key,
            "name": name,
            "description": description,
            "theme": theme,
            "page_url": page_url,
        }

    monkeypatch.setattr(sources, "create_data_source", fake_create_data_source)

    created = await sources.create_source(
        sources.DataSourceCreate(
            source_key=" my_hdx ",
            name=" Humanitarian Data Exchange ",
            description=" Global datasets ",
            theme=" Humanitarian ",
            page_url="https://data.humdata.org/dataset",
        ),
        PRINCIPAL,
    )

    assert captured_arguments == {
        "source_key": "my_hdx",
        "name": "Humanitarian Data Exchange",
        "description": "Global datasets",
        "theme": "Humanitarian",
        "page_url": "https://data.humdata.org/dataset",
    }
    assert created.source_key == "my_hdx"


@pytest.mark.parametrize("source_key", ["   ", "My HDX", "_hidden"])
async def test_create_source_rejects_invalid_source_keys(source_key):
    from app.routes import sources

    importlib.reload(sources)

    with pytest.raises(ValidationError):
        sources.DataSourceCreate(
            source_key=source_key,
            name="Source",
            description="",
            theme="General",
            page_url="https://example.org/source",
        )


async def test_create_source_rejects_duplicate_source_key(monkeypatch):
    from app.routes import sources

    importlib.reload(sources)
    _allow_source_creation(sources, monkeypatch)

    async def fake_create_data_source(
        source_key: str,
        name: str,
        description: str,
        theme: str,
        page_url: str,
    ):
        raise sources.DuplicateDataSourceKeyError(
            f"Data source key {source_key!r} already exists."
        )

    monkeypatch.setattr(sources, "create_data_source", fake_create_data_source)

    with pytest.raises(HTTPException) as exception_info:
        await sources.create_source(
            sources.DataSourceCreate(
                source_key="my_hdx",
                name="Humanitarian Data Exchange",
                description="Global datasets.",
                theme="Humanitarian",
                page_url="https://data.humdata.org/dataset",
            ),
            PRINCIPAL,
        )

    assert exception_info.value.status_code == 409
    assert "already exists" in str(exception_info.value.detail)


async def test_create_source_rejects_reserved_seed_key(database, monkeypatch):
    from app.routes import sources

    importlib.reload(sources)
    _allow_source_creation(sources, monkeypatch)
    await database.init_database()

    with pytest.raises(HTTPException) as exception_info:
        await sources.create_source(
            sources.DataSourceCreate(
                source_key="who_gho_indicators",
                name="User override",
                description="Should not be allowed.",
                theme="Custom",
                page_url="https://example.org/override",
            ),
            PRINCIPAL,
        )

    assert exception_info.value.status_code == 400
    assert "reserved by the application" in str(exception_info.value.detail)
