from __future__ import annotations

from dataclasses import replace

import pytest
from app.api.presenters import public_collected_dataset
from app.db.connection import _fetchone, _require_database_pool
from app.db.schema import CURRENT_SCHEMA_VERSION
from helpers.inspection import stored_datasets

from collector.storage.models import CollectedDataset

pytestmark = pytest.mark.anyio

IDENTITY = {
    "platform": "zenodo",
    "repository_origin": "https://zenodo.org",
    "kind": "dataset",
    "native_id": "123",
    "persistent_id": "10.5281/zenodo.123",
    "version": "1.2",
}


def record(url="https://zenodo.org/records/123", identity=None):
    return CollectedDataset(
        dataset_url=url,
        title="Health survey",
        description="Health survey data",
        publisher="",
        hosting_platform="zenodo",
        uploader="",
        dataset_signals={},
        record_identity=IDENTITY if identity is None else identity,
    )


async def test_identity_survives_save_reads_search_and_api_presentation(database):
    await database.init_database()
    await database.save_collected_datasets("https://zenodo.org", [record()])
    stored = (await stored_datasets(database))[0]
    assert stored.record_identity == IDENTITY
    assert public_collected_dataset(stored).record_identity == IDENTITY
    searched = await database.search_collected_datasets("health survey")
    assert searched[0].record_identity == IDENTITY


async def test_fallback_without_identity_does_not_erase_a_previous_observation(database):
    await database.init_database()
    await database.save_collected_datasets("https://zenodo.org", [record()])
    await database.save_collected_datasets("https://zenodo.org", [record(identity={})])
    assert (await stored_datasets(database))[0].record_identity == IDENTITY


async def test_reference_only_fallback_preserves_identity_fields_observed_by_api(database):
    await database.init_database()
    await database.save_collected_datasets("https://zenodo.org", [record()])
    sparse_identity = {**IDENTITY, "persistent_id": "", "version": ""}
    await database.save_collected_datasets("https://zenodo.org", [record(identity=sparse_identity)])
    assert (await stored_datasets(database))[0].record_identity == IDENTITY


async def test_file_and_parent_record_remain_distinct(database):
    await database.init_database()
    file = record(
        "https://zenodo.org/records/123/files/survey.csv",
        {
            **IDENTITY,
            "kind": "file",
            "native_id": "123/files/survey.csv",
            "persistent_id": "",
            "parent_persistent_id": IDENTITY["persistent_id"],
        },
    )
    await database.save_collected_datasets("https://zenodo.org", [record(), file])
    saved = await stored_datasets(database)
    assert len(saved) == 2
    assert {item.record_identity["kind"] for item in saved} == {"file", "dataset"}


async def test_explicit_version_urls_remain_distinct(database):
    await database.init_database()
    first = record("https://dataverse.example.org/dataset.xhtml?persistentId=doi:X&version=1.0")
    second = replace(
        first,
        dataset_url=first.dataset_url.replace("version=1.0", "version=2.0"),
        record_identity={**IDENTITY, "version": "2.0"},
    )
    await database.save_collected_datasets("https://dataverse.example.org", [first, second])
    assert len(await stored_datasets(database)) == 2


async def test_reinitialization_preserves_datasets_and_record_identity(database):
    await database.init_database()
    await database.save_collected_datasets("https://zenodo.org", [record()])
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    await database.init_database()
    stored = (await stored_datasets(database))[0]
    assert stored.title == "Health survey"
    assert stored.record_identity == IDENTITY
    async with _require_database_pool().connection() as connection:
        row = await _fetchone(connection, "SELECT MAX(version) AS version FROM schema_migrations")
    assert row["version"] == CURRENT_SCHEMA_VERSION
