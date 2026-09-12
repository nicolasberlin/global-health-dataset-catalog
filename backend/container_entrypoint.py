"""Install container-local egress rules, then start the API without privileges."""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
from pathlib import Path

from collector.network_policy import BLOCKED_IPV4, BLOCKED_IPV6, PUBLIC_IPV6


def build_rules(
    database_addresses: list[str], resolver_addresses: list[str], extra: str = ""
) -> str:
    """Render nft input using validated addresses only, never arbitrary config text."""
    if not database_addresses or not resolver_addresses:
        raise ValueError("Egress requires database and DNS addresses.")

    rules = [
        "table inet collector_egress {",
        "chain output {",
        # Run after conntrack, but before Docker's embedded-DNS output DNAT.
        "type filter hook output priority -150; policy drop;",
        # Permit replies to incoming API connections, not arbitrary preexisting egress.
        "ct direction reply ct state established,related accept",
    ]
    for value in resolver_addresses:
        address = ipaddress.ip_address(value)
        family = "ip" if address.version == 4 else "ip6"
        rules.extend(
            [
                f"{family} daddr {address} udp dport 53 accept",
                f"{family} daddr {address} tcp dport 53 accept",
            ]
        )
    for value in database_addresses:
        address = ipaddress.ip_address(value)
        family = "ip" if address.version == 4 else "ip6"
        rules.append(f"{family} daddr {address} tcp dport 5432 accept")
    for value in extra.split(","):
        if value.strip():
            network = ipaddress.ip_network(value.strip(), strict=True)
            family = "ip" if network.version == 4 else "ip6"
            rules.append(f"{family} daddr {network} drop")
    for value in BLOCKED_IPV4:
        rules.append(f"ip daddr {value} drop")
    for value in BLOCKED_IPV6:
        rules.append(f"ip6 daddr {value} drop")
    rules.extend(
        [
            "meta nfproto ipv4 tcp dport { 80, 443 } accept",
            f"ip6 daddr {PUBLIC_IPV6} tcp dport {{ 80, 443 }} accept",
            # IPv6 needs neighbour discovery; hop limit 255 confines this to the link.
            "icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert } ip6 hoplimit 255 accept",
            "}",
            "}",
        ]
    )
    return "\n".join(rules) + "\n"


def install_egress_rules() -> None:
    # The Compose database service is a trusted, fixed name; never take an
    # exception hostname or port from a collector URL.
    database_addresses = sorted(
        {result[4][0] for result in socket.getaddrinfo("postgres", 5432, type=socket.SOCK_STREAM)}
    )
    resolver_addresses = []
    for line in Path("/etc/resolv.conf").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            resolver_addresses.append(parts[1])
    rules = build_rules(
        database_addresses, resolver_addresses, os.environ.get("EGRESS_BLOCKED_CIDRS", "")
    )
    # Replace only our table, atomically, on restarts. Leave Docker's DNS/NAT rules intact.
    existing = subprocess.run(
        ["nft", "list", "table", "inet", "collector_egress"], capture_output=True
    )
    if existing.returncode == 0:
        rules = "delete table inet collector_egress\n" + rules
    subprocess.run(["nft", "-f", "-"], input=rules, text=True, check=True)


def main() -> None:
    if len(sys.argv) < 2:
        raise ValueError("An application command is required.")
    install_egress_rules()
    # NET_ADMIN is available only during bootstrap. The API and all children
    # have an empty capability bounding set and cannot remove the firewall.
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
            *sys.argv[1:],
        ],
    )


if __name__ == "__main__":
    main()
