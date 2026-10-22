"""Exercise the standalone API over TCP and across actual process restarts."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import httpx
import pytest
from app.db.connection import _require_database_pool

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[1]
SESSION_SECRET = "fixture-public-session-secret-0000000000000000"


class APIProcess:
    def __init__(self, database_url, directory, *, gate=None, mode="public"):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.log_path = directory / "api-process.log"
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join([str(ROOT / "backend"), str(ROOT / "tests"), str(ROOT)]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "DATABASE_URL": database_url,
            "API_AUTH_MODE": "public",
            "API_SESSION_SECRET": SESSION_SECRET,
            "API_PUBLIC_ORIGIN": self.base_url,
            "API_ALLOW_INSECURE_HTTP_SESSIONS": "true",
            "API_CORS_ORIGINS": "http://frontend.example",
            "RCP_DEEPSEEK_API_KEY": "synthetic-fixture-key",
            "RCP_GEMMA_MEDITRON_API_KEY": "synthetic-fixture-key",
            "RCP_APERTUS_MEDITRON_API_KEY": "synthetic-fixture-key",
            "COLLECTION_BROWSER_URL": "",
            "SEARCH_MAX_CONCURRENCY": "1",
            "CLASSIFICATION_MAX_CONCURRENCY": "1",
            "COLLECTION_MAX_CONCURRENCY": "1",
            "WORKER_SHUTDOWN_TIMEOUT_SECONDS": "2",
        }
        if gate:
            self.env["API_FIXTURE_COLLECTION_GATE"] = str(gate)
        self.mode = mode
        if mode == "local":
            self.env["API_AUTH_MODE"] = "local"
        self.directory = directory
        self.client_env = directory / "client.env"
        self.client_env.write_text(
            f"API_BASE_URL={self.base_url}\nAPI_CLIENT_MODE={mode}\n"
            f"API_PUBLIC_ORIGIN={self.base_url}\n"
        )
        self.process = None
        self.log_file = None

    async def start(self):
        self.log_file = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "api_verification_harness:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--no-access-log",
                "--no-proxy-headers",
            ],
            cwd=ROOT,
            env=self.env,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            async with httpx.AsyncClient(base_url=self.base_url, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        pytest.fail(self.log_path.read_text())
                    try:
                        if (await client.get("/ready", timeout=0.5)).status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.05)
                pytest.fail("API did not become ready:\n" + self.log_path.read_text())
        except BaseException:
            await self.stop()
            raise

    async def stop(self, *, crash=False):
        if self.process is not None and self.process.poll() is None:
            if crash:
                self.process.kill()
            else:
                self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait, timeout=5)
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    @asynccontextmanager
    async def client(self, *, owner="alice"):
        if self.mode == "local":
            async with httpx.AsyncClient(
                base_url=self.base_url, trust_env=False, timeout=3
            ) as client:
                yield client
            return
        path = self.directory / f"{owner}.cookies"
        jar = MozillaCookieJar(str(path))
        if path.exists():
            jar.load(ignore_discard=True)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Origin": self.base_url},
            cookies=jar,
            trust_env=False,
            timeout=3,
        ) as client:
            response = await client.post("/session")
            assert response.status_code == 204
            yield client
            for cookie in client.cookies.jar:
                jar.set_cookie(cookie)
            path.touch(mode=0o600, exist_ok=True)
            jar.save(ignore_discard=True)


async def wait_for_completion(client, progress_url):
    deadline = time.monotonic() + 20
    snapshot = {}
    while time.monotonic() < deadline:
        response = await client.get(progress_url)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        snapshot = response.json()
        if not snapshot["polling_required"]:
            return snapshot
        await asyncio.sleep(0.05)
    pytest.fail("Search did not finish: " + json.dumps(snapshot))


async def submit(client, key="runtime-first"):
    response = await client.post(
        "/collector/searches", json={"query": "malaria"}, headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    assert response.headers["Location"] == response.json()["progress_url"]
    return response.json()


async def run_standalone_client(server, output, *arguments, expected_returncode=0):
    # Inject isolated fixed paths without adding configuration flags to the real CLI.
    entrypoint = (
        "import sys; from pathlib import Path; from scripts import api_client as client; "
        "client.DEFAULT_ENV_FILE = Path(sys.argv[1]); "
        "client.DEFAULT_OUTPUT_FILE = Path(sys.argv[2]); "
        "client.DEFAULT_COOKIE_FILE = Path(sys.argv[3]); "
        "client.DEFAULT_PENDING_FILE = Path(sys.argv[4]); "
        "client.POLL_INTERVAL_SECONDS = 0.05; "
        "sys.exit(client.main(sys.argv[5:]))"
    )
    result = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable, "-c", entrypoint,
            str(server.client_env), str(output), str(server.directory / "alice.cookies"),
            str(server.directory / "pending-search.json"), *arguments,
        ],
        env={"PATH": os.environ.get("PATH", "")},
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == expected_returncode, result.stdout + result.stderr
    assert SESSION_SECRET not in result.stdout + result.stderr + output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
    return json.loads(output.read_text())


async def test_real_server_collects_without_client_then_restores_after_restart(database, tmp_path):
    gate = tmp_path / "hold-collection"
    gate.touch()
    server = APIProcess(os.environ["DATABASE_URL"], tmp_path, gate=gate)
    await server.start()
    try:
        accepted = await run_standalone_client(
            server, tmp_path / "accepted.json", "--query", "malaria",
            "--timeout", "0.03", expected_returncode=1,
        )
        assert accepted["command_state"] == "acknowledged"
        command = accepted["command"]
        deadline = time.monotonic() + 15
        while not Path(str(gate) + ".started").exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert Path(str(gate) + ".started").exists(), server.log_path.read_text()
        gate.unlink()
        # No browser or HTTP client drives the three worker stages.
        async def persisted_result():
            async with _require_database_pool().connection() as connection:
                cursor = await connection.execute("SELECT count(*) FROM collected_datasets")
                return (await cursor.fetchone())["count"]

        deadline = time.monotonic() + 20
        while not await persisted_result() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert await persisted_result() == 1, server.log_path.read_text()
        async with server.client() as client:
            completed = await wait_for_completion(client, command["progress_url"])
            assert completed["origin"] == "online"
            assert completed["outcome"] == "results", completed
            assert len(completed["dataset_ids"]) == 1
            candidate = completed["items"][0]
            assert candidate["classification_progress"]["succeeded"] == 3
            job = candidate["automatic_collection"]["job"]
            assert job["classification_progress"]["succeeded"] == 3
            assert job["saved_count"] == 1
            datasets = (await client.get(
                "/collector/collected-datasets/by-id", params={"ids": completed["dataset_ids"]},
            )).json()["items"]
            assert datasets[0]["validation_results"][0]["status"] == "available"
            assert datasets[0]["distributions"][0]["url"].endswith("/malaria.csv")
            trace_response = await client.get(
                f"/collector/searches/{command['search_id']}/diagnostics",
            )
            assert trace_response.status_code == 200
            assert trace_response.json()["collections"]
            assert "synthetic-fixture-key" not in trace_response.text

        await server.stop()
        await server.start()
        report = await run_standalone_client(
            server, tmp_path / "restored.json", "--latest",
        )
        assert report["progress"]["dataset_ids"] == completed["dataset_ids"]
        assert len(report["datasets"]) == 1
        assert report["diagnostics"]["context"]["search_id"] == command["search_id"]
        async with server.client() as client:
            latest = await client.get("/collector/searches/latest")
            assert latest.status_code == 200
            assert latest.json()["search_id"] == command["search_id"]
            restored = await wait_for_completion(client, command["progress_url"])
            assert restored["dataset_ids"] == completed["dataset_ids"]
            replay = await client.post(
                "/collector/searches", json={"query": "malaria"},
                headers={"Idempotency-Key": accepted["idempotency_key"]},
            )
            assert replay.status_code == 200
            assert replay.json()["search_id"] == command["search_id"]
            local_command = await submit(client, "runtime-local")
            local = await wait_for_completion(client, local_command["progress_url"])
            assert local["origin"] == "database"
            assert local["dataset_ids"] == completed["dataset_ids"]
            assert local["items"] == []
        async with server.client(owner="bob") as client:
            assert (await client.get(command["progress_url"])).status_code == 404
        assert await persisted_result() == 1
    finally:
        await server.stop()


async def test_process_crash_during_collection_can_be_retried_over_http(database, tmp_path):
    gate = tmp_path / "hold-collection"
    gate.touch()
    server = APIProcess(os.environ["DATABASE_URL"], tmp_path, gate=gate)
    await server.start()
    try:
        async with server.client() as client:
            command = await submit(client)
        deadline = time.monotonic() + 15
        while not Path(str(gate) + ".started").exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert Path(str(gate) + ".started").exists(), server.log_path.read_text()
        await server.stop(crash=True)
        gate.unlink()
        await server.start()
        async with server.client() as client:
            interrupted = await wait_for_completion(client, command["progress_url"])
            assert interrupted["errors"], interrupted
            assert interrupted["dataset_ids"] == []
            discovery_retry = await client.post(
                f"/collector/searches/{command['search_id']}/retry", json={},
                headers={"Idempotency-Key": "runtime-discovery-already-complete"},
            )
            assert discovery_retry.status_code == 409
            job_id = interrupted["items"][0]["automatic_collection"]["job"]["id"]
            retry = await client.post(
                f"/collector/collection-jobs/{job_id}/retry",
                headers={"Idempotency-Key": "runtime-retry-after-crash"},
            )
            assert retry.status_code == 202, retry.text
            assert retry.json()["job"]["id"] == job_id
            completed = await wait_for_completion(client, command["progress_url"])
            assert completed["outcome"] == "results", completed
            assert completed["attempt"] == 1
            assert len(completed["dataset_ids"]) == 1
            assert completed["items"][0]["classification_progress"]["succeeded"] == 3
            replay = await client.post(
                f"/collector/collection-jobs/{job_id}/retry",
                headers={"Idempotency-Key": "runtime-retry-after-crash"},
            )
            assert replay.status_code == 202 and replay.json()["job"]["status"] == "done"
    finally:
        await server.stop()


async def test_native_local_api_and_python_client_need_no_credentials(database, tmp_path):
    server = APIProcess(os.environ["DATABASE_URL"], tmp_path, mode="local")
    await server.start()
    try:
        report = await run_standalone_client(server, tmp_path / "local.json", "--query", "malaria")
        assert report["command_state"] == "acknowledged"
        assert report["progress"]["outcome"] == "results"
        async with server.client() as client:
            assert (await client.get("/session")).status_code == 405
            schema = (await client.get("/openapi.json")).json()
            assert "security" not in schema["paths"]["/collector/searches"]["post"]
            replay = await client.post(
                "/collector/searches",
                json={"query": "malaria"},
                headers={"Idempotency-Key": report["idempotency_key"]},
            )
            assert replay.status_code == 200
        async with _require_database_pool().connection() as connection:
            cursor = await connection.execute("SELECT DISTINCT owner_id FROM search_sessions")
            assert await cursor.fetchall() == [{"owner_id": "local-user"}]
    finally:
        await server.stop()
