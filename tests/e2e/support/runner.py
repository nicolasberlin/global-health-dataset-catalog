"""Start and stop the real Uvicorn process for the pytest HTTP client."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from tests.helpers.paths import PROJECT_ROOT


@dataclass
class RunningAPI:
    base_url: str
    process: subprocess.Popen
    log_path: Path

    def check_alive(self):
        assert self.process.poll() is None, (
            f"Uvicorn exited with {self.process.returncode}:\n{self.log_path.read_text()}"
        )

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        assert self.process.returncode in (0, -signal.SIGTERM), (
            self.process.returncode,
            self.log_path.read_text(),
        )


@contextmanager
def running_api(*, database_url, directory, external_services):
    scenario_path = directory / "search-scenario.json"
    scenario_path.write_text(json.dumps(external_services.scenario))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT / "backend"), str(PROJECT_ROOT)]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "DATABASE_URL": database_url,
        "E2E_SCENARIO_FILE": str(scenario_path),
        "E2E_RUNTIME_DIR": str(directory),
        "E2E_API_PORT": str(port),
        "API_AUTH_MODE": "local",
        "API_CORS_ORIGINS": "",
        "COLLECTION_BROWSER_URL": "",
        "RCP_DEEPSEEK_MODEL": "fixture-deepseek",
        "RCP_DEEPSEEK_API_KEY": "fixture-deepseek-key",
        "RCP_GEMMA_MEDITRON_MODEL": "fixture-gemma",
        "RCP_GEMMA_MEDITRON_API_KEY": "fixture-gemma-key",
        "RCP_APERTUS_MEDITRON_MODEL": "fixture-apertus",
        "RCP_APERTUS_MEDITRON_API_KEY": "fixture-apertus-key",
        "SEARCH_MAX_CONCURRENCY": "1",
        "CLASSIFICATION_MAX_CONCURRENCY": "1",
        "COLLECTION_MAX_CONCURRENCY": "1",
        "WORKER_SHUTDOWN_TIMEOUT_SECONDS": "5",
    }
    log_path = directory / "search-server.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("server.py"))],
            cwd=directory,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        server = RunningAPI(f"http://127.0.0.1:{port}", process, log_path)
        failure = None
        try:
            deadline = time.monotonic() + 45
            with httpx.Client(base_url=server.base_url, timeout=0.5, trust_env=False) as probe:
                while time.monotonic() < deadline:
                    server.check_alive()
                    external_services.assert_no_violations()
                    try:
                        response = probe.get("/ready")
                    except httpx.TransportError:
                        time.sleep(0.1)
                        continue
                    if response.status_code == 200:
                        assert response.json() == {"status": "ok"}
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("API did not become ready:\n" + log_path.read_text())
                health = probe.get("/health")
                assert health.status_code == 200 and health.json() == {"status": "ok"}
            yield server
        except BaseException as exception:
            failure = exception
            raise
        finally:
            try:
                server.stop()
            except BaseException as cleanup_error:
                if failure is None:
                    raise
                failure.add_note(f"Server cleanup also failed: {cleanup_error}")
            if failure is not None:
                failure.add_note("Uvicorn log:\n" + log_path.read_text())
                failure.add_note("External calls:\n" + external_services.journal.read_text())
