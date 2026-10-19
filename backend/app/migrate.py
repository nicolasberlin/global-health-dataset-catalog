"""Run or verify versioned migrations independently of the HTTP server."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.database import (
    close_database_pool,
    init_database,
    open_database_pool,
    validate_database_schema,
)
from app.db.application_lock import application_lock
from app.db.schema import CURRENT_SCHEMA_VERSION
from collector.observability import configure_operational_logging, emit_event


async def run_migrations(*, check_only: bool = False) -> None:
    async with application_lock():
        await open_database_pool()
        try:
            if check_only:
                await validate_database_schema()
            else:
                await init_database()
        finally:
            await close_database_pool()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the schema without DDL.")
    options = parser.parse_args()
    configure_operational_logging()
    try:
        asyncio.run(run_migrations(check_only=options.check))
    except Exception:
        emit_event("database_migration", outcome="failed")
        print("Database schema operation failed; check database access and ownership.",
              file=sys.stderr)
        return 1
    emit_event("database_migration", outcome="success")
    print(f"Database schema {CURRENT_SCHEMA_VERSION} verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
