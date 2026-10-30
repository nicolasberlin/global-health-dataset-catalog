"""Conservative public-address policy shared by HTTP and container egress."""

from __future__ import annotations

import ipaddress

# Explicit ranges keep the policy consistent across supported Python versions.
BLOCKED_IPV4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
)
# Only native global unicast IPv6 is allowed. This also excludes IPv4-mapped,
# NAT64, scoped/link-local and multicast addresses. Block transition mechanisms
# (including Teredo/6to4) so embedded private IPv4 cannot bypass the policy.
PUBLIC_IPV6 = "2000::/3"
BLOCKED_IPV6 = ("2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20")
_BLOCKED = tuple(ipaddress.ip_network(value) for value in (*BLOCKED_IPV4, *BLOCKED_IPV6))
_PUBLIC_IPV6 = ipaddress.ip_network(PUBLIC_IPV6)


def is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not address.is_global or address.is_multicast:
        return False
    if address.version == 6 and (address not in _PUBLIC_IPV6 or address.scope_id is not None):
        return False
    return not any(address in network for network in _BLOCKED if address.version == network.version)
