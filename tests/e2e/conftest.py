"""Prepare real services and an HTTP client for each deterministic search scenario.

Run with --confcutdir=tests/e2e to load these fixtures without the repository's
source-based application fixtures. --noconftest would disable this fixture too.
"""

from __future__ import annotations

import shutil

import httpx
import psycopg
import pytest

from tests.e2e.scenarios import RECORDS, SCENARIOS
from tests.e2e.support.client import ExternalServiceJournal, SearchWorkflowChecks
from tests.e2e.support.runner import running_api
from tests.helpers.postgres import disposable_postgres


@pytest.fixture(params=list(SCENARIOS))
def scenario(request):
    case = SCENARIOS[request.param]
    return {
        "name": request.param,
        "records": {key: RECORDS[key] for key in case["responses"]},
        **case,
    }


@pytest.fixture
def postgres_url(tmp_path):
    docker = shutil.which("docker")
    assert docker is not None, "Docker is required for disposable E2E PostgreSQL"
    with disposable_postgres(docker, tmp_path, host_access=True) as database_url:
        yield database_url


@pytest.fixture
def mock_external_services(scenario, tmp_path):
    journal = ExternalServiceJournal(scenario, tmp_path)
    yield journal
    # api_server depends on this fixture, so its shutdown has already completed.
    if journal.verified:
        journal.assert_expected_calls(log=False)
    else:
        journal.assert_no_violations()


@pytest.fixture
def api_server(postgres_url, tmp_path, mock_external_services):
    with running_api(
        database_url=postgres_url,
        directory=tmp_path,
        external_services=mock_external_services,
    ) as server:
        yield server


@pytest.fixture
def client(api_server):
    with httpx.Client(
        base_url=api_server.base_url,
        timeout=3,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as http_client:
        yield http_client


@pytest.fixture
def workflow(postgres_url, scenario, api_server, mock_external_services):
    with psycopg.connect(
        postgres_url,
        autocommit=True,
        connect_timeout=3,
        options="-c default_transaction_read_only=on",
    ) as observer:
        assert observer.execute("SELECT count(*) FROM collected_datasets").fetchone() == (0,)
        yield SearchWorkflowChecks(scenario, observer, api_server, mock_external_services)
