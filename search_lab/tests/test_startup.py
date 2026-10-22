import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("has_private_config", [False, True])
def test_startup_loads_only_its_own_optional_configuration(tmp_path, has_private_config):
    root = tmp_path / "project"
    lab = root / "search_lab"
    lab.mkdir(parents=True)
    script = lab / "start.sh"
    shutil.copyfile(Path(__file__).parents[1] / "start.sh", script)
    (root / ".env.local").write_text("LAB_DATABASE_URL=must-not-load-root-config\n")
    if has_private_config:
        (lab / ".env").write_text(
            "LAB_DATABASE_URL=postgresql://localhost/lab-private\n"
            "API_AUTH_MODE=local\n"
        )

    python_output = tmp_path / "python.json"
    npm_output = tmp_path / "npm.json"
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['STARTUP_PYTHON_OUTPUT']).write_text(json.dumps({\n"
        "    'database': os.getenv('LAB_DATABASE_URL'),\n"
        "    'auth': os.getenv('API_AUTH_MODE'),\n"
        "    'pythonpath': os.getenv('PYTHONPATH'),\n"
        "    'cwd': os.getcwd(),\n"
        "    'args': sys.argv[1:],\n"
        "}))\n"
    )
    python.chmod(0o755)
    commands = tmp_path / "commands"
    commands.mkdir()
    npm = commands / "npm"
    npm.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys, time\n"
        "deadline = time.monotonic() + 5\n"
        "while not pathlib.Path(os.environ['STARTUP_PYTHON_OUTPUT']).exists():\n"
        "    if time.monotonic() > deadline: sys.exit(1)\n"
        "    time.sleep(0.01)\n"
        "pathlib.Path(os.environ['STARTUP_NPM_OUTPUT']).write_text(json.dumps({\n"
        "    'database': os.getenv('LAB_DATABASE_URL'),\n"
        "    'auth': os.getenv('API_AUTH_MODE'),\n"
        "    'args': sys.argv[1:],\n"
        "}))\n"
    )
    npm.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "LAB_DATABASE_URL": "postgresql://localhost/manual-export",
        "API_AUTH_MODE": "local",
        "PYTHONPATH": "existing-package-path",
        "STARTUP_PYTHON_OUTPUT": str(python_output),
        "STARTUP_NPM_OUTPUT": str(npm_output),
    }

    subprocess.run(["sh", str(script)], cwd=tmp_path, env=env, check=True, timeout=10)

    backend = json.loads(python_output.read_text())
    frontend = json.loads(npm_output.read_text())
    expected_database = "postgresql://localhost/" + (
        "lab-private" if has_private_config else "manual-export"
    )
    assert backend["database"] == frontend["database"] == expected_database
    assert backend["auth"] == frontend["auth"] == "local"
    assert backend["cwd"] == str(root)
    assert backend["pythonpath"] == "backend:.:existing-package-path"
    assert backend["args"][:3] == ["-m", "uvicorn", "search_lab.backend.app:app"]
    assert frontend["args"] == ["--prefix", "search_lab/frontend", "run", "dev"]
