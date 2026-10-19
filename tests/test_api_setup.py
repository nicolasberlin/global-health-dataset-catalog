"""Verify the local setup creates a usable client without replacing private settings."""

import json
import shlex
import shutil
from pathlib import Path

import pytest

import scripts.setup_api as api_setup

TEMPLATE = Path(__file__).resolve().parents[1] / ".env.api.example"
PRIVATE_TOKEN = "private-existing-token-" + "x" * 32


@pytest.fixture
def project(tmp_path):
    shutil.copyfile(TEMPLATE, tmp_path / ".env.api.example")
    return tmp_path


def settings(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, raw = line.split("=", 1)
        parsed = shlex.split(raw, comments=True)
        values[key.strip()] = parsed[0] if parsed else ""
    return values


def replace_setting(path, key, value):
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(
        "\n".join(f"{key}={value}" if line.startswith(f"{key}=") else line for line in lines)
        + "\n",
        encoding="utf-8",
    )


def test_initialize_creates_matching_private_configuration(project):
    backend, client = api_setup.initialize(project)
    assert (backend, client) == (project / ".env.api", project / ".env.api-client")
    server_values, client_values = settings(backend), settings(client)
    tokens = json.loads(server_values["API_ACCESS_TOKENS"])
    assert list(tokens) == ["local-test"]
    assert len(tokens["local-test"]) >= 32
    assert client_values["API_TOKEN"] == tokens["local-test"]
    assert server_values["API_PORT"] == "8001"
    assert server_values["API_BIND_ADDRESS"] == "127.0.0.1"
    assert client_values["API_BASE_URL"] == "http://127.0.0.1:8001"
    template_values = settings(project / ".env.api.example")
    assert server_values["POSTGRES_PASSWORD"] != template_values["POSTGRES_PASSWORD"]
    assert len(server_values["POSTGRES_PASSWORD"]) >= 32
    for name in (
        "RCP_DEEPSEEK_API_KEY", "RCP_GEMMA_MEDITRON_API_KEY", "RCP_APERTUS_MEDITRON_API_KEY",
    ):
        assert server_values[name] == template_values[name]
    for path in (backend, client):
        assert path.stat().st_mode & 0o777 == 0o600


def test_initialize_generates_independent_secrets_for_each_checkout(project, tmp_path):
    first_backend, _ = api_setup.initialize(project)
    other = tmp_path / "other-checkout"
    other.mkdir()
    shutil.copyfile(TEMPLATE, other / ".env.api.example")
    second_backend, _ = api_setup.initialize(other)
    first, second = settings(first_backend), settings(second_backend)
    assert first["POSTGRES_PASSWORD"] != second["POSTGRES_PASSWORD"]
    assert first["API_ACCESS_TOKENS"] != second["API_ACCESS_TOKENS"]


def test_initialize_uses_custom_owner_and_port(project):
    backend, client = api_setup.initialize(project, owner="demo-client", port=8123)
    server_values, client_values = settings(backend), settings(client)
    assert server_values["API_PORT"] == "8123"
    assert client_values["API_BASE_URL"] == "http://127.0.0.1:8123"
    assert client_values["API_TOKEN"] == json.loads(
        server_values["API_ACCESS_TOKENS"],
    )["demo-client"]


def test_initialize_preserves_existing_keys_comments_and_credentials(project):
    backend, client = api_setup.initialize(project)
    replace_setting(backend, "RCP_DEEPSEEK_API_KEY", "private-rcp-key")
    with backend.open("a", encoding="utf-8") as stream:
        stream.write("\n# Keep this deployment note.\n")
    before = {path: path.read_bytes() for path in (backend, client)}
    assert api_setup.initialize(project) == (backend, client)
    assert {path: path.read_bytes() for path in before} == before


def test_existing_backend_requires_selection_of_an_existing_owner(project):
    backend, client = api_setup.initialize(project)
    client.unlink()
    replace_setting(
        backend, "API_ACCESS_TOKENS", f"'{json.dumps({'site': PRIVATE_TOKEN})}'",
    )
    original = backend.read_bytes()
    with pytest.raises(api_setup.SetupError) as error:
        api_setup.initialize(project)
    assert PRIVATE_TOKEN not in str(error.value)
    assert backend.read_bytes() == original
    assert not client.exists()
    result = api_setup.initialize(project, owner="site")
    assert result == (backend, client)
    assert settings(client)["API_TOKEN"] == PRIVATE_TOKEN
    assert backend.read_bytes() == original


def test_existing_client_mismatch_does_not_replace_either_configuration(project):
    backend, client = api_setup.initialize(project)
    replace_setting(client, "API_TOKEN", PRIVATE_TOKEN)
    original = {path: path.read_bytes() for path in (backend, client)}
    with pytest.raises(api_setup.SetupError) as error:
        api_setup.initialize(project)
    assert PRIVATE_TOKEN not in str(error.value)
    assert {path: path.read_bytes() for path in original} == original


def test_orphaned_client_is_preserved_instead_of_generating_a_different_backend(project):
    client = project / ".env.api-client"
    client.write_text(f"API_TOKEN={PRIVATE_TOKEN}\n", encoding="utf-8")
    original = client.read_bytes()
    with pytest.raises(api_setup.SetupError) as error:
        api_setup.initialize(project)
    assert PRIVATE_TOKEN not in str(error.value)
    assert client.read_bytes() == original
    assert not (project / ".env.api").exists()


@pytest.mark.parametrize("raw", ["'{broken-json-private-secret'", "'{\"local-test\":\"short\"}'"])
def test_invalid_existing_tokens_are_rejected_without_modifying_files(project, raw):
    backend, client = api_setup.initialize(project)
    replace_setting(backend, "API_ACCESS_TOKENS", raw)
    original = {path: path.read_bytes() for path in (backend, client)}
    with pytest.raises(api_setup.SetupError) as error:
        api_setup.initialize(project)
    assert "broken-json-private-secret" not in str(error.value)
    assert {path: path.read_bytes() for path in original} == original


@pytest.mark.parametrize("name", [".env.api", ".env.api-client"])
def test_existing_symlink_is_rejected_without_touching_its_target(project, name):
    backend, client = api_setup.initialize(project)
    path = project / name
    target = project / "private-original"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    original = {item: item.read_bytes() for item in (backend, client, target)}
    with pytest.raises(api_setup.SetupError):
        api_setup.initialize(project)
    assert path.is_symlink()
    assert {item: item.read_bytes() for item in original} == original


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port_does_not_create_configuration(project, port):
    with pytest.raises(api_setup.SetupError):
        api_setup.initialize(project, port=port)
    assert not (project / ".env.api").exists()
    assert not (project / ".env.api-client").exists()


def test_main_uses_the_project_root_and_does_not_print_generated_secrets(
    project, monkeypatch, capsys,
):
    monkeypatch.setattr(api_setup, "PROJECT_ROOT", project)
    assert api_setup.main([]) == 0
    backend, client = project / ".env.api", project / ".env.api-client"
    output = capsys.readouterr()
    printed = output.out + output.err
    assert settings(backend)["POSTGRES_PASSWORD"] not in printed
    assert settings(client)["API_TOKEN"] not in printed


def test_main_reports_configuration_error_without_printing_credentials(
    project, monkeypatch, capsys,
):
    _, client = api_setup.initialize(project)
    replace_setting(client, "API_TOKEN", PRIVATE_TOKEN)
    monkeypatch.setattr(api_setup, "PROJECT_ROOT", project)
    assert api_setup.main([]) == 1
    output = capsys.readouterr()
    assert output.out or output.err
    assert PRIVATE_TOKEN not in output.out + output.err


@pytest.mark.parametrize("port", ["0", "65536", "not-a-number"])
def test_cli_rejects_invalid_ports_before_writing_configuration(project, monkeypatch, port):
    monkeypatch.setattr(api_setup, "PROJECT_ROOT", project)
    try:
        exit_code = api_setup.main(["--port", port])
    except SystemExit as error:
        exit_code = error.code
    assert exit_code in {1, 2}
    assert not (project / ".env.api").exists()
    assert not (project / ".env.api-client").exists()
