"""Disposable PostgreSQL services shared by packaging and HTTP workflow tests."""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from uuid import uuid4

import pytest


def _run(*command, cwd, stdin=None, timeout=300):
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exception:
        pytest.fail(
            f"Command timed out: {command!r}\n"
            f"stdout:\n{exception.stdout!r}\nstderr:\n{exception.stderr!r}",
            pytrace=False,
        )
    assert result.returncode == 0, (
        f"Command failed: {command!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


@contextmanager
def disposable_postgres(docker, directory, *, host_access=False):
    """Yield a Docker network, or a loopback database URL when host_access is set."""
    network = f"backend-startup-test-{uuid4().hex}"
    container = network + "-postgres"
    _run(docker, "network", "create", network, cwd=directory)
    failure = None
    try:
        publication = ["--publish", "127.0.0.1::5432"] if host_access else []
        _run(
            docker,
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--network",
            network,
            "--network-alias",
            "postgres",
            "--env",
            "POSTGRES_USER=packaging",
            "--env",
            "POSTGRES_PASSWORD=packaging-test-only",
            "--env",
            "POSTGRES_DB=packaging",
            *publication,
            "postgres:16",
            cwd=directory,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = subprocess.run(
                [
                    docker,
                    "exec",
                    container,
                    "pg_isready",
                    "--host",
                    "127.0.0.1",
                    "--username",
                    "packaging",
                    "--dbname",
                    "packaging",
                    "--timeout",
                    "2",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            logs = _run(docker, "logs", container, cwd=directory)
            pytest.fail(f"Disposable PostgreSQL did not become ready:\n{logs.stdout}{logs.stderr}")
        if host_access:
            binding = _run(docker, "port", container, "5432/tcp", cwd=directory).stdout.strip()
            address, _, port = binding.rpartition(":")
            assert address == "127.0.0.1" and 1 <= int(port) <= 65535, binding
            yield f"postgresql://packaging:packaging-test-only@127.0.0.1:{port}/packaging"
        else:
            yield network
    except BaseException as exception:
        failure = exception
        raise
    finally:
        cleanup_errors = []
        for arguments in (("rm", "--force", "--volumes", container), ("network", "rm", network)):
            try:
                cleanup = subprocess.run(
                    [docker, *arguments], capture_output=True, text=True, timeout=15, check=False
                )
                if cleanup.returncode:
                    raise RuntimeError(cleanup.stdout + cleanup.stderr)
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as cleanup_error:
                cleanup_errors.append(str(cleanup_error))
        if cleanup_errors:
            message = "Disposable service cleanup failed:\n" + "\n".join(cleanup_errors)
            if failure is not None:
                failure.add_note(message)
            else:
                raise RuntimeError(message)
