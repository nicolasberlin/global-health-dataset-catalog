"""Firewall protects the browser, including direct traffic bypassing its proxy."""

from __future__ import annotations

import ipaddress
import os
import subprocess
from pathlib import Path

from collector.network.policy import BLOCKED_IPV4, BLOCKED_IPV6, PUBLIC_IPV6


def rules(resolvers, extra=""):
    lines = [
        "table inet browser_egress {",
        "chain output {",
        "type filter hook output priority -150; policy drop;",
        "ct direction reply ct state established,related accept",
        "ip daddr 127.0.0.1 tcp dport 8899 accept",
    ]
    for value in resolvers:
        ip = ipaddress.ip_address(value)
        family = "ip" if ip.version == 4 else "ip6"
        lines += [
            f"{family} daddr {ip} udp dport 53 accept",
            f"{family} daddr {ip} tcp dport 53 accept",
        ]
    for value in extra.split(","):
        if value.strip():
            network = ipaddress.ip_network(value.strip(), strict=True)
            family = "ip" if network.version == 4 else "ip6"
            lines.append(f"{family} daddr {network} drop")
    for value in BLOCKED_IPV4:
        lines.append(f"ip daddr {value} drop")
    for value in BLOCKED_IPV6:
        lines.append(f"ip6 daddr {value} drop")
    lines += [
        "meta nfproto ipv4 tcp dport 443 accept",
        f"ip6 daddr {PUBLIC_IPV6} tcp dport 443 accept",
        "icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert } ip6 hoplimit 255 accept",
        "}",
        "}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    resolvers = [
        line.split()[1]
        for line in Path("/etc/resolv.conf").read_text().splitlines()
        if line.startswith("nameserver ")
    ]
    existing = subprocess.run(
        ["nft", "list", "table", "inet", "browser_egress"], capture_output=True
    )
    text = rules(resolvers, os.getenv("EGRESS_BLOCKED_CIDRS", ""))
    if existing.returncode == 0:
        text = "delete table inet browser_egress\n" + text
    subprocess.run(["nft", "-f", "-"], input=text, text=True, check=True)
    os.environ["BROWSER_NETWORK_ISOLATED"] = "1"
    os.execvp(
        "setpriv",
        [
            "setpriv",
            "--reuid=10001",
            "--regid=10001",
            "--clear-groups",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
            "--no-new-privs",
            "--",
            "/app/browser/start.sh",
        ],
    )
