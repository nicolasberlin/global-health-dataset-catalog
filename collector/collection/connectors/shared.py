"""Small parsing helpers shared by explicit platform connectors."""

from __future__ import annotations

from urllib.parse import urlsplit


def repository_origin(url: str, hosts: tuple[str, ...]) -> str | None:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
    except ValueError:
        return None
    return f"https://{parsed.hostname}"


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def positive_id(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return str(int(value))
    return ""

