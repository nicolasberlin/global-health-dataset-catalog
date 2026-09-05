from __future__ import annotations

import importlib
import os
import uuid
from urllib.parse import quote

import psycopg
import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _database_url_for_schema(database_url: str, schema_name: str) -> str:
    options = quote(f"-csearch_path={schema_name},public", safe="")
    separator = "&" if "?" in database_url else "?"
    return f"{database_url}{separator}options={options}"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL database tests.")

    try:
        with psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=3,
        ):
            pass
    except psycopg.OperationalError as exception:
        pytest.fail(
            "TEST_DATABASE_URL is set, but PostgreSQL is not reachable: "
            f"{exception}",
            pytrace=False,
        )

    return database_url


@pytest.fixture
async def database(monkeypatch, test_database_url):
    schema_name = f"test_{uuid.uuid4().hex}"
    with psycopg.connect(
        test_database_url,
        autocommit=True,
        connect_timeout=3,
    ) as connection:
        connection.execute(f'CREATE SCHEMA "{schema_name}"')

    monkeypatch.setenv(
        "DATABASE_URL",
        _database_url_for_schema(test_database_url, schema_name),
    )

    from app import database as database_module

    database_module = importlib.reload(database_module)
    await database_module.open_database_pool()
    try:
        yield database_module
    finally:
        await database_module.close_database_pool()
        with psycopg.connect(
            test_database_url,
            autocommit=True,
            connect_timeout=3,
        ) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
