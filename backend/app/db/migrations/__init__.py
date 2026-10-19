"""The initial release has one migration for an empty database."""

from __future__ import annotations

from types import MappingProxyType

from .v001 import _migrate_0_to_1 as _migrate_0_to_1

MIGRATIONS = MappingProxyType({0: _migrate_0_to_1})


def migration_for_version(version: int):
    try:
        return MIGRATIONS[version]
    except KeyError:
        raise RuntimeError(f"No migration registered for schema version {version}.") from None
