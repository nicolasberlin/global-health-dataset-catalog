"""The local launcher starts only the existing database and a loopback API."""

import subprocess
from types import SimpleNamespace

import pytest

from scripts import start_api
from scripts.setup_api import SetupError


def values():
    return {
        "API_AUTH_MODE": "local",
        "API_BIND_ADDRESS": "127.0.0.1",
        "API_PORT": "8123",
        "POSTGRES_PASSWORD": "keep-this-database-password",
        "RCP_DEEPSEEK_API_KEY": "synthetic",
        "RCP_GEMMA_MEDITRON_API_KEY": "synthetic",
        "RCP_APERTUS_MEDITRON_API_KEY": "synthetic",
    }


def test_launcher_waits_for_existing_database_and_executes_one_local_worker(tmp_path, monkeypatch):
    (tmp_path / ".env.api").write_text("".join(f"{k}={v}\n" for k, v in values().items()))
    calls, executed = [], []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(start_api.subprocess, "run", run)
    monkeypatch.setattr(start_api.os, "execvpe", lambda *args: executed.append(args))
    start_api.start(tmp_path)
    assert calls[0][-3:] == ["up", "-d", "postgres"]
    assert "pg_isready" in calls[1]
    _, command, environment = executed[0]
    assert command[-3:] == ["--workers", "1", "--no-proxy-headers"]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8123"
    assert environment["DATABASE_URL"].endswith("@127.0.0.1:5432/global_health")
    assert not any("down" in command or "-v" in command for command in calls)


@pytest.mark.parametrize(
    "change",
    [
        {"API_AUTH_MODE": "public"},
        {"API_BIND_ADDRESS": "0.0.0.0"},
        {"RCP_DEEPSEEK_API_KEY": "replace-me"},
    ],
)
def test_unsafe_or_incomplete_config_never_starts_a_service(change):
    with pytest.raises(SetupError):
        start_api.local_environment({**values(), **change})


def test_database_failure_never_starts_uvicorn(tmp_path, monkeypatch):
    (tmp_path / ".env.api").write_text("".join(f"{k}={v}\n" for k, v in values().items()))

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["docker", "compose"])

    monkeypatch.setattr(start_api.subprocess, "run", fail)
    monkeypatch.setattr(start_api.os, "execvpe", lambda *args: pytest.fail("must not launch API"))
    with pytest.raises(subprocess.CalledProcessError):
        start_api.start(tmp_path)


def test_local_database_defaults_do_not_leak_from_another_shell_configuration(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "another-project")
    monkeypatch.setenv("POSTGRES_DB", "another-database")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    environment = start_api.local_environment(values())
    assert environment["POSTGRES_USER"] == "global_health"
    assert environment["POSTGRES_DB"] == "global_health"
    assert environment["POSTGRES_PORT"] == "5432"
    assert "another-project" not in environment["DATABASE_URL"]


def test_default_api_address_cannot_be_overridden_by_inherited_shell_values(monkeypatch):
    configuration = values()
    configuration.pop("API_PORT")
    configuration.pop("API_BIND_ADDRESS")
    monkeypatch.setenv("API_PORT", "8002")
    monkeypatch.setenv("API_BIND_ADDRESS", "0.0.0.0")
    environment = start_api.local_environment(configuration)
    assert environment["API_PORT"] == "8001"
    assert environment["API_BIND_ADDRESS"] == "127.0.0.1"
