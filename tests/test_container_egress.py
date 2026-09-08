"""Opt-in smoke test of the real Docker firewall and privilege drop.

Build backend/Dockerfile, then set EGRESS_TEST_IMAGE to that image name.
Creates only disposable containers/networks, without host mounts or published ports.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid

import pytest

IMAGE = os.environ.get("EGRESS_TEST_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="Set EGRESS_TEST_IMAGE for Docker egress tests.")

SERVER = """
import socket, threading, time
def serve(family, port):
    sock = socket.socket(family)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.bind(('::' if family == socket.AF_INET6 else '0.0.0.0', port))
    sock.listen()
    def accept():
        while True:
            conn, _ = sock.accept()
            conn.close()
    threading.Thread(target=accept, daemon=True).start()
for family in (socket.AF_INET, socket.AF_INET6):
    for port in (80, 443, 5432, 8080):
        serve(family, port)
print('READY', flush=True)
while True:
    time.sleep(1)
"""

CLIENT = """
import os, socket, subprocess
from pathlib import Path
from collector.fetch import fetch_public_html
assert os.getuid() == 10001
status = Path('/proc/self/status').read_text()
for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
    value = next(line.split()[1] for line in status.splitlines() if line.startswith(name + ':'))
    assert int(value, 16) == 0, name
assert 'NoNewPrivs:\\t1' in status
# The API cannot remove its own policy after bootstrap.
assert subprocess.run(['nft', 'delete', 'table', 'inet', 'collector_egress'],
                      capture_output=True).returncode != 0
# Docker DNS must remain functional after installation of the output policy.
addresses = {entry[4][0] for entry in socket.getaddrinfo('postgres', 5432, type=socket.SOCK_STREAM)}
assert addresses
for address in addresses:
    with socket.create_connection((address, 5432), timeout=2):
        pass
    for port in (80, 443, 8080):
        try:
            socket.create_connection((address, port), timeout=0.3).close()
        except OSError:
            pass
        else:
            raise AssertionError(f'Internal egress allowed: {address}:{port}')
# A local HTTP server is also unreachable through loopback.
listener = socket.socket()
listener.bind(('127.0.0.1', 8080))
listener.listen()
try:
    socket.create_connection(('127.0.0.1', 8080), timeout=0.3).close()
except OSError:
    pass
else:
    raise AssertionError('Loopback egress allowed')
listener.close()
# Exercise real DNS, pinned sockets and a valid HTTPS certificate together.
page = fetch_public_html('https://example.com/', timeout=10)
assert page.status_code == 200
print('Egress, DNS, PostgreSQL exception, TLS and privilege checks passed.')
"""


def test_container_egress_and_privilege_drop():
    docker = os.environ.get("EGRESS_TEST_DOCKER", "docker")
    name = f"collector-egress-test-{uuid.uuid4().hex[:10]}"

    def run(*args, check=True, timeout=60):
        return subprocess.run(
            [docker, *args], capture_output=True, text=True, check=check, timeout=timeout
        )

    run("network", "create", "--ipv6", name)
    try:
        run(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            name,
            "--network-alias",
            "postgres",
            "--entrypoint",
            "python",
            IMAGE,
            "-c",
            SERVER,
        )
        for _ in range(50):
            if "READY" in run("logs", name).stdout:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Disposable TCP server did not start")
        # Prove the internal HTTP ports are reachable before the firewall is installed.
        run(
            "run",
            "--rm",
            "--network",
            name,
            "--entrypoint",
            "python",
            IMAGE,
            "-c",
            "import socket; socket.create_connection(('postgres', 80), timeout=2).close()",
        )
        capabilities = [
            "--cap-drop=ALL",
            "--cap-add=NET_ADMIN",
            "--cap-add=SETUID",
            "--cap-add=SETGID",
            "--cap-add=SETPCAP",
            "--security-opt=no-new-privileges:true",
        ]
        result = run(
            "run",
            "--name",
            name + "-client",
            "--network",
            name,
            *capabilities,
            IMAGE,
            "python",
            "-c",
            CLIENT,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        # Restart the same container: rule replacement must remain valid and atomic.
        result = run("start", "-a", name + "-client", check=False)
        state = json.loads(run("inspect", name + "-client").stdout)[0]["State"]
        assert state["ExitCode"] == 0, result.stdout + result.stderr
        # Missing NET_ADMIN must fail closed before the requested application command.
        result = run(
            "run",
            "--rm",
            "--network",
            name,
            "--cap-drop=ALL",
            IMAGE,
            "python",
            "-c",
            "print('APPLICATION_STARTED')",
            check=False,
        )
        assert result.returncode != 0
        assert "APPLICATION_STARTED" not in result.stdout
    finally:
        run("rm", "-f", name + "-client", name, check=False)
        run("network", "rm", name, check=False)
