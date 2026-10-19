"""Prepare private configuration for a local API test, without extra Python packages."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SetupError(RuntimeError):
    pass


def _read_values(path):
    if path.is_symlink() or not path.is_file():
        raise SetupError(f"{path.name} must be a regular file, not a symbolic link.")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise SetupError(f"Could not read {path.name}.") from None
    return _parse_values(content, path.name)


def _parse_values(content, filename):
    values = {}
    for number, line in enumerate(content.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        key = key.strip()
        try:
            parts = shlex.split(raw, comments=True)
        except ValueError:
            parts = [None, None]
        if (not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                or key in values or len(parts) > 1):
            raise SetupError(f"{filename} : line {number} is invalid (expected KEY=value).")
        values[key] = parts[0] if parts else ""
    return values


def _port(value):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise SetupError("The port must be an integer between 1 and 65535.") from None
    if isinstance(value, bool) or str(number) != str(value) or not 1 <= number <= 65535:
        raise SetupError("The port must be an integer between 1 and 65535.")
    return number


def _replace_settings(template, replacements):
    lines = []
    remaining = dict(replacements)
    for line in template.splitlines():
        key = line.partition("=")[0].strip()
        if key in remaining:
            line = f"{key}={shlex.quote(str(remaining.pop(key)))}"
        lines.append(line)
    if remaining:
        raise SetupError("The .env.api.example template is incomplete.")
    return "\n".join(lines) + "\n"


def _create_private(path, content):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SetupError(f"{path.name} already exists; nothing was overwritten.") from None
    except OSError:
        raise SetupError(f"Could not create {path.name}.") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def initialize(root, *, owner="local-test", port=None):
    """Create matching configuration files, preserving all existing credentials."""
    root = Path(root)
    if not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", owner):
        raise SetupError("--owner accepts 1-100 characters from A-Z a-z 0-9 . _ : -.")
    requested_port = _port(port) if port is not None else None
    backend, client = root / ".env.api", root / ".env.api-client"
    backend_exists = backend.exists() or backend.is_symlink()
    client_exists = client.exists() or client.is_symlink()
    if client_exists and not backend_exists:
        raise SetupError(
            ".env.api-client exists without .env.api. Existing settings were preserved; "
            "check the files before preparing a new local test."
        )
    new_backend = None
    if backend_exists:
        values = _read_values(backend)
    else:
        template = root / ".env.api.example"
        _read_values(template)
        try:
            new_backend = _replace_settings(template.read_text(encoding="utf-8"), {
                "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
                "API_ACCESS_TOKENS": json.dumps({owner: secrets.token_urlsafe(32)}),
                "API_PORT": requested_port or 8001,
                "API_BIND_ADDRESS": "127.0.0.1",
            })
        except (OSError, UnicodeError):
            raise SetupError("Could not read .env.api.example.") from None
        values = _parse_values(new_backend, ".env.api")
    actual_port = _port(values.get("API_PORT", "8001"))
    if requested_port is not None and requested_port != actual_port:
        raise SetupError(
            "--port differs from API_PORT in .env.api; existing settings were preserved."
        )
    bind = values.get("API_BIND_ADDRESS", "127.0.0.1")
    if bind not in {"127.0.0.1", "0.0.0.0", "::1", "::"}:
        raise SetupError("The existing configuration does not point to a local test setup.")
    address = "[::1]" if ":" in bind else "127.0.0.1"
    base_url = f"http://{address}:{actual_port}"
    password = values.get("POSTGRES_PASSWORD", "")
    if not password or password.startswith("replace-"):
        raise SetupError("Set POSTGRES_PASSWORD in .env.api before continuing.")
    try:
        tokens = json.loads(values.get("API_ACCESS_TOKENS", ""))
    except ValueError:
        raise SetupError(
            "API_ACCESS_TOKENS in .env.api must be a valid JSON object."
        ) from None
    if not isinstance(tokens, dict) or owner not in tokens:
        raise SetupError(
            "The requested owner is missing from API_ACCESS_TOKENS. "
            "Use --owner with an existing owner name; no token was replaced."
        )
    token = tokens[owner]
    if (not isinstance(token, str) or not 32 <= len(token) <= 512
            or token != token.strip() or token.startswith("replace-")
            or any(ord(char) < 32 or ord(char) > 126 for char in token)):
        raise SetupError("The selected token in .env.api must contain 32-512 valid characters.")
    if client_exists:
        existing = _read_values(client)
        if (existing.get("API_BASE_URL", "").rstrip("/") != base_url
                or existing.get("API_TOKEN") != token
                or existing.get("API_TEST_AUTH", "token") != "token"):
            raise SetupError(
                ".env.api-client contains different settings. "
                "The file was preserved; check its address, authentication mode and token."
            )
    if new_backend is not None:
        _create_private(backend, new_backend)
    if not client_exists:
        _create_private(client, (
            "# Generated for local testing. Keep this file private.\n"
            f"API_BASE_URL={base_url}\n"
            f"API_TOKEN={shlex.quote(token)}\n"
        ))
    return backend, client


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="local-test", help="Token owner name")
    parser.add_argument(
        "--port", type=int, help="Local port (default: 8001 for a new configuration)",
    )
    args = parser.parse_args(argv)
    try:
        backend, _ = initialize(PROJECT_ROOT, owner=args.owner, port=args.port)
    except (SetupError, OSError) as exc:
        detail = (
            str(exc) if isinstance(exc, SetupError) else "Could not write the configuration."
        )
        print(f"Error: {detail}", file=sys.stderr)
        return 1
    print(f"Configuration files prepared: {backend}")
    print("Open .env.api and fill in the three RCP keys (RCP_*_API_KEY).")
    print("The PostgreSQL password and client access token are already configured.")
    print("Existing files and credentials are preserved.")
    print("\nStart the API and PostgreSQL locally:")
    print("docker compose --env-file .env.api -f docker-compose.api.yml up -d --build")
    print("\nThen run a search:")
    print('python3 scripts/test_api.py --query "pneumonia"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
