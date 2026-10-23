"""The independently installable API must work without optional client modules."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app import main
from httpx import ASGITransport, AsyncClient

CORE_PATHS = {
    "/health",
    "/ready",
    "/session",
    "/collector/searches",
    "/collector/searches/latest",
    "/collector/searches/{search_id}/progress",
    "/collector/searches/{search_id}/diagnostics",
    "/collector/collected-datasets/by-id",
}


def test_core_imports_and_openapi_work_when_extensions_cannot_be_imported(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = """
import importlib.abc
import sys
class BlockPrivateInterface(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'interface_web' or fullname.startswith('interface_web.'):
            raise AssertionError(
                'The core API tried to import the private web interface: ' + fullname
            )
sys.meta_path.insert(0, BlockPrivateInterface())
from app.main import create_app
application = create_app()
assert set(application.openapi()['paths']) == set(sys.argv[1:])
assert not any(name == 'interface_web' or name.startswith('interface_web.') for name in sys.modules)
"""
    environment = {
        **os.environ,
        "API_AUTH_MODE": "local",
        "PYTHONPATH": os.pathsep.join([str(root / "backend"), str(root)]),
    }
    subprocess.run(
        [sys.executable, "-c", code, *sorted(CORE_PATHS)],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.anyio
async def test_readiness_belongs_to_the_requested_application(monkeypatch):
    monkeypatch.setattr(main, "workers_ready", lambda: True)
    monkeypatch.setattr(main, "validate_default_classifier_configuration", lambda: None)
    monkeypatch.setattr(main, "check_database_readiness", AsyncMock())
    first, second = main.create_app(), main.create_app()
    first.state.ready = True
    second.state.ready = False
    async with AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as client:
        assert (await client.get("/ready")).status_code == 200
    async with AsyncClient(transport=ASGITransport(app=second), base_url="http://test") as client:
        assert (await client.get("/ready")).status_code == 503
