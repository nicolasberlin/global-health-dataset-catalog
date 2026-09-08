from __future__ import annotations

import subprocess

import pytest

from backend import container_entrypoint


def test_firewall_failure_prevents_application_start(monkeypatch):
    monkeypatch.setattr("sys.argv", ["entrypoint", "uvicorn", "app.main:app"])

    def fail():
        raise subprocess.CalledProcessError(1, ["nft"])

    monkeypatch.setattr(container_entrypoint, "install_egress_rules", fail)
    monkeypatch.setattr("os.execvp", lambda *a: pytest.fail("API must not start without firewall"))
    with pytest.raises(subprocess.CalledProcessError):
        container_entrypoint.main()


@pytest.mark.parametrize(
    "addresses,resolvers,extra",
    [
        ([], ["127.0.0.11"], ""),
        (["172.20.0.2"], [], ""),
        (["172.20.0.2; accept"], ["127.0.0.11"], ""),
        (["172.20.0.2"], ["127.0.0.11"], "0.0.0.0/0; accept"),
    ],
)
def test_invalid_egress_configuration_is_rejected(addresses, resolvers, extra):
    with pytest.raises(ValueError):
        container_entrypoint.build_rules(addresses, resolvers, extra)
