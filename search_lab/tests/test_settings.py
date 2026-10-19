import json

import httpx
import pytest

from search_lab.backend import settings
from search_lab.scenarios import experiment, run


def test_lab_default_storage_is_separate_from_api_and_independent_of_working_directory(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("LAB_EVIDENCE_DIR", raising=False)
    monkeypatch.setenv("LAB_DATABASE_URL", "postgresql://localhost/lab")
    monkeypatch.chdir(tmp_path)

    configured = settings.Settings.configured()

    assert configured.evidence_dir == settings.LAB_ROOT / "data" / "evidence"
    assert settings.LAB_ROOT == settings.ROOT / "search_lab"
    assert settings.evidence_directory() == configured.evidence_dir


def test_lab_custom_storage_is_shared_with_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_EVIDENCE_DIR", "custom-lab-data")
    monkeypatch.setenv("LAB_DATABASE_URL", "postgresql://localhost/lab")
    monkeypatch.chdir(tmp_path)

    assert settings.Settings.configured().evidence_dir == tmp_path / "custom-lab-data"
    assert settings.evidence_directory() == tmp_path / "custom-lab-data"


@pytest.fixture(params=["default", "custom"])
def lab_storage(request, tmp_path, monkeypatch):
    default = tmp_path / "search_lab" / "data" / "evidence"
    monkeypatch.setattr(settings, "DEFAULT_EVIDENCE_DIR", default)
    monkeypatch.delenv("LAB_EVIDENCE_DIR", raising=False)
    if request.param == "custom":
        custom = tmp_path / "custom-lab-data"
        monkeypatch.setenv("LAB_EVIDENCE_DIR", str(custom))
        return custom
    return default


def test_reproduction_writes_beneath_shared_lab_storage(lab_storage, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["run", "api", "https://example.org/data", "--offline-json", "fixture.json"],
    )
    monkeypatch.setattr(run, "fingerprint", lambda: {"git_commit": "fixture"})
    monkeypatch.setattr(run, "execute", lambda *args, **kwargs: {"status": "succeeded"})

    run.main()

    output = json.loads(capsys.readouterr().out)
    files = list((lab_storage / "reproductions").glob("*.json"))
    assert len(files) == 1
    assert output["evidence_file"] == str(files[0])
    saved = json.loads(files[0].read_text())
    assert saved["document_type"] == "search_lab_reproduction"
    assert saved["offline"] is True
    assert saved["result"] == {"status": "succeeded"}


def test_experiment_writes_beneath_shared_lab_storage(lab_storage, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["experiment", "search", "--include-ai"])
    monkeypatch.setattr(experiment, "target_database", lambda name: "unused-local-database")
    diagnostics = {"context": {"search_id": "experiment-search", "query": "HIV"}}

    def respond(request):
        if request.url.path == "/collector/searches":
            return httpx.Response(200, json={"search_id": "experiment-search"})
        if request.url.path.endswith("/progress"):
            return httpx.Response(200, json={"polling_required": False})
        assert request.url.path.endswith("/diagnostics")
        return httpx.Response(200, json=diagnostics)

    client = httpx.Client(
        base_url="http://127.0.0.1:8011", transport=httpx.MockTransport(respond)
    )
    monkeypatch.setattr(experiment.httpx, "Client", lambda **kwargs: client)

    experiment.main()

    files = list((lab_storage / "experiments").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == diagnostics
    assert str(files[0]) in capsys.readouterr().out
