"""Start PostgreSQL in Docker and the local API on loopback, without access tokens."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib.parse import quote

try:
    from scripts.setup_api import PROJECT_ROOT, SetupError, _port, _read_values, validate_local
except ModuleNotFoundError:  # Direct invocation: python scripts/start_api.py
    from setup_api import PROJECT_ROOT, SetupError, _port, _read_values, validate_local


def local_environment(values):
    validate_local(values)
    for key in (
        "RCP_DEEPSEEK_API_KEY",
        "RCP_GEMMA_MEDITRON_API_KEY",
        "RCP_APERTUS_MEDITRON_API_KEY",
    ):
        if not values.get(key) or values[key].startswith("replace-"):
            raise SetupError(f"Set {key} in .env.api before starting a real search API.")
    environment = {**os.environ, **values}
    user = quote(values.get("POSTGRES_USER", "global_health"), safe="")
    password = quote(values["POSTGRES_PASSWORD"], safe="")
    database = quote(values.get("POSTGRES_DB", "global_health"), safe="")
    port = _port(values.get("POSTGRES_PORT", "5432"))
    environment.update(
        API_AUTH_MODE="local",
        API_BIND_ADDRESS=values.get("API_BIND_ADDRESS", "127.0.0.1"),
        API_PORT=str(values.get("API_PORT", "8001")),
        POSTGRES_USER=values.get("POSTGRES_USER", "global_health"),
        POSTGRES_DB=values.get("POSTGRES_DB", "global_health"),
        POSTGRES_PORT=str(port),
        DATABASE_URL=f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}",
    )
    return environment


def start(root=PROJECT_ROOT, *, application="app.main:app"):
    config = root / ".env.api"
    environment = local_environment(_read_values(config))
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), environment.get("PYTHONPATH", "")) if part
    )
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(config),
        "-f",
        str(root / "docker-compose.local.yml"),
    ]
    # No volume is removed, renamed or recreated by this launcher.
    subprocess.run([*compose, "up", "-d", "postgres"], cwd=root, env=environment, check=True)
    deadline = time.monotonic() + 60
    while True:
        probe = subprocess.run(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "pg_isready",
                "-U",
                environment.get("POSTGRES_USER", "global_health"),
                "-d",
                environment.get("POSTGRES_DB", "global_health"),
            ],
            cwd=root,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
        if probe.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise SetupError(
                "PostgreSQL is not ready. Inspect docker compose logs; data was preserved."
            )
        time.sleep(0.5)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        application,
        "--app-dir",
        str(root / "backend"),
        "--host",
        environment["API_BIND_ADDRESS"],
        "--port",
        environment["API_PORT"],
        "--workers",
        "1",
        "--no-proxy-headers",
    ]
    print("Starting the local API. PostgreSQL stays running after Ctrl+C.", flush=True)
    os.execvpe(sys.executable, command, environment)


def main():
    try:
        start()
    except (SetupError, OSError, subprocess.SubprocessError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, SetupError)
            else "Local startup failed. Check Docker and run setup_api.py."
        )
        print(f"Error: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
