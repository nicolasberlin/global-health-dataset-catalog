"""Prepare private local API settings without access tokens or extra packages."""

from __future__ import annotations

import argparse
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
        if (
            not separator
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or key in values
            or len(parts) > 1
        ):
            raise SetupError(f"{filename}: line {number} is invalid (expected KEY=value).")
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


def validate_local(values):
    """Validate before starting services or changing an existing configuration."""
    if values.get("API_AUTH_MODE", "local") != "local":
        raise SetupError(
            "Local setup requires API_AUTH_MODE=local. Existing files were preserved."
        )
    if values.get("API_BIND_ADDRESS", "127.0.0.1") not in {"127.0.0.1", "::1"}:
        raise SetupError("The local API must bind to 127.0.0.1 or ::1.")
    password = values.get("POSTGRES_PASSWORD", "")
    if not password or password.startswith("replace-"):
        raise SetupError("Set POSTGRES_PASSWORD in .env.api before continuing.")
    _port(values.get("API_PORT", "8001"))
    _port(values.get("POSTGRES_PORT", "5432"))


def initialize(root, *, port=None):
    """Prepare a local server and client, preserving existing files and database secrets."""
    root = Path(root)
    requested_port = _port(port) if port is not None else None
    backend, client = root / ".env.api", root / ".env.api-client"
    if (client.exists() or client.is_symlink()) and not backend.exists():
        raise SetupError(
            ".env.api-client exists without .env.api; existing settings were preserved."
        )
    new_backend = None
    if backend.exists() or backend.is_symlink():
        values = _read_values(backend)
    else:
        template = root / ".env.api.example"
        _read_values(template)
        new_backend = _replace_settings(
            template.read_text(encoding="utf-8"),
            {
                "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            },
        )
        if requested_port is not None and requested_port != 8001:
            new_backend += f"API_PORT={requested_port}\n"
        values = _parse_values(new_backend, ".env.api")
    validate_local(values)
    actual_port = _port(values.get("API_PORT", "8001"))
    if requested_port is not None and requested_port != actual_port:
        raise SetupError("--port differs from API_PORT; existing settings were preserved.")
    address = "[::1]" if values.get("API_BIND_ADDRESS") == "::1" else "127.0.0.1"
    base_url = f"http://{address}:{actual_port}"
    client_exists = client.exists() or client.is_symlink()
    if client_exists:
        existing = _read_values(client)
        if (
            existing.get("API_CLIENT_MODE", "local") != "local"
            or existing.get("API_BASE_URL", "http://127.0.0.1:8001").rstrip("/") != base_url
        ):
            raise SetupError(
                ".env.api-client uses different local settings. "
                "The file was preserved; follow docs/ONBOARDING.md."
            )
    if new_backend is not None:
        _create_private(backend, new_backend)
    if not client_exists:
        client_content = "API_CLIENT_MODE=local\n"
        if base_url != "http://127.0.0.1:8001":
            client_content += f"API_BASE_URL={base_url}\n"
        _create_private(client, client_content)
    return backend, client


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, help="Local port (default: 8001)")
    args = parser.parse_args(argv)
    try:
        backend, _ = initialize(PROJECT_ROOT, port=args.port)
    except (SetupError, OSError) as exc:
        detail = str(exc) if isinstance(exc, SetupError) else "Could not prepare the configuration."
        print(f"Error: {detail}", file=sys.stderr)
        return 1
    print(f"Local configuration prepared: {backend}")
    print("Fill in the three RCP model keys in .env.api. No API access token is needed.")
    print("Existing values and database credentials are preserved.")
    print("Start: uv run --locked python scripts/start_api.py")
    print('Search: uv run --locked python scripts/api_client.py --query "pneumonia"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
