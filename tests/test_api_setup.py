"""Local setup preserves private settings and requires no API access token."""

import shutil
from pathlib import Path

import pytest

from scripts.setup_api import SetupError, _read_values, initialize

TEMPLATE = Path(__file__).resolve().parents[1] / ".env.api.example"


@pytest.fixture
def project(tmp_path):
    shutil.copyfile(TEMPLATE, tmp_path / ".env.api.example")
    return tmp_path


def test_setup_creates_private_local_settings_without_access_tokens(project):
    backend, client = initialize(project)
    server, caller = _read_values(backend), _read_values(client)
    assert server["API_AUTH_MODE"] == "local"
    assert "API_PORT" not in server
    assert caller == {"API_CLIENT_MODE": "local"}
    assert len(server["POSTGRES_PASSWORD"]) >= 32
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (backend, client))
    before = {p: p.read_bytes() for p in (backend, client)}
    assert initialize(project) == (backend, client)
    assert {p: p.read_bytes() for p in before} == before


def test_setup_custom_port_and_database_password_are_stable(project):
    backend, client = initialize(project, port=8123)
    assert _read_values(backend)["API_PORT"] == "8123"
    assert _read_values(client)["API_BASE_URL"] == "http://127.0.0.1:8123"
    original = backend.read_bytes()
    with pytest.raises(SetupError, match="differs"):
        initialize(project, port=9000)
    assert backend.read_bytes() == original


def test_setup_does_not_need_address_overrides_for_the_default_port(project):
    backend, client = initialize(project, port=8001)
    assert "API_PORT" not in _read_values(backend)
    assert "API_BASE_URL" not in _read_values(client)
    assert initialize(project) == (backend, client)


@pytest.mark.parametrize(
    "setting",
    [
        "API_AUTH_MODE=unknown",
        "API_BIND_ADDRESS=0.0.0.0",
        "API_AUTH_MODE=public",
    ],
)
def test_incompatible_or_exposed_settings_are_preserved_and_rejected(project, setting):
    backend, client = initialize(project)
    key = setting.split("=")[0]
    backend.write_text(
        "\n".join(
            line for line in backend.read_text().splitlines() if not line.startswith(key + "=")
        )
        + "\n"
        + setting
        + "\n"
    )
    before = {p: p.read_bytes() for p in (backend, client)}
    with pytest.raises(SetupError):
        initialize(project)
    assert {p: p.read_bytes() for p in before} == before


def test_setup_never_replaces_an_orphaned_client_or_symlink(project):
    client = project / ".env.api-client"
    client.write_text("API_BASE_URL=http://127.0.0.1:8123\n")
    with pytest.raises(SetupError):
        initialize(project)
    assert client.read_text() == "API_BASE_URL=http://127.0.0.1:8123\n"
    assert not (project / ".env.api").exists()
    client.unlink()
    target = project / "keep.env"
    target.write_text("untouched")
    (project / ".env.api").symlink_to(target)
    with pytest.raises(SetupError):
        initialize(project)
    assert target.read_text() == "untouched"


@pytest.mark.parametrize("port", [0, -1, 65536, True, "bad"])
def test_invalid_port_creates_no_configuration(project, port):
    with pytest.raises(SetupError):
        initialize(project, port=port)
    assert not (project / ".env.api").exists()
