"""Container network bootstraps import successfully without application dependencies."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def fresh_python(script):
    # The browser image installs no Python application packages. -I -S recreates
    # that import boundary even when pytest itself runs inside a populated venv.
    bootstrap = "import sys\nsys.path.insert(0, sys.argv[1])\n"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", bootstrap + dedent(script), str(ROOT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_policy_and_firewall_bootstraps_remain_standard_library_only():
    fresh_python("""
        import ipaddress
        import runpy
        from pathlib import Path

        from collector.network.policy import (
            BLOCKED_IPV4, BLOCKED_IPV6, is_public_address,
        )

        root = Path(sys.argv[1])
        backend = runpy.run_path(str(root / "backend/container_entrypoint.py"))
        browser = runpy.run_path(str(root / "browser/container_entrypoint.py"))
        backend_rules = backend["build_rules"](["172.18.0.2"], ["127.0.0.11"])
        browser_rules = browser["rules"](["127.0.0.11"])
        assert all(value in backend_rules and value in browser_rules
                   for value in (*BLOCKED_IPV4, *BLOCKED_IPV6))
        assert is_public_address(ipaddress.ip_address("8.8.8.8"))
        assert not is_public_address(ipaddress.ip_address("127.0.0.1"))
        assert not is_public_address(ipaddress.ip_address("2001:db8::1"))
        assert not any(name in sys.modules for name in (
            "collector.network.fetch", "collector.network.transport",
            "collector.network.resolver", "collector.config", "collector.budget",
            "fastapi", "psycopg", "pydantic",
        ))
    """)


def test_browser_proxy_imports_the_moved_fetcher_without_backend_packages():
    fresh_python("""
        import runpy
        from pathlib import Path

        from collector.network.fetch import _connect_public

        root = Path(sys.argv[1])
        proxy = runpy.run_path(str(root / "browser/public_proxy.py"))
        assert proxy["_connect_public"] is _connect_public
        assert _connect_public.__module__ == "collector.network.fetch"
        assert "collector.network.resolver" in sys.modules
        assert "collector.network.transport" in sys.modules
        assert not any(name in sys.modules for name in (
            "app", "fastapi", "psycopg", "pydantic",
        ))
    """)
