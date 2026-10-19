"""Optional fresh-database profile; never resets or drops an existing database."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from search_lab.backend.settings import evidence_directory


def target_database(name):
    if not re.fullmatch(r"ghdc_lab_[a-z0-9_]{1,40}", name):
        raise ValueError("Use a dedicated database name starting with ghdc_lab_.")
    source = os.environ["DATABASE_URL"]
    if conninfo_to_dict(source).get("dbname") == name:
        raise ValueError("The experiment database must differ from DATABASE_URL.")
    return make_conninfo(source, dbname=name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "start", "search"])
    parser.add_argument("--name", default="ghdc_lab_experiments")
    parser.add_argument("--query", default="HIV")
    parser.add_argument("--include-ai", action="store_true")
    args = parser.parse_args()
    target = target_database(args.name)
    if args.action == "init":
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (args.name,)
            ).fetchone()
            if exists:
                raise RuntimeError("Database already exists. Choose another name for a fresh run.")
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.name)))
        print("Created dedicated database:", args.name)
    elif args.action == "start":
        env = {**os.environ, "DATABASE_URL": target, "API_AUTH_MODE": "local"}
        argv = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8011",
            "--no-proxy-headers",
        ]
        os.execve(sys.executable, argv, env)
    else:
        if not args.include_ai:
            parser.error(
                "A complete search requires --include-ai to authorize external/model work."
            )
        with httpx.Client(base_url="http://127.0.0.1:8011", timeout=20, trust_env=False) as client:
            response = client.post(
                "/collector/searches",
                json={"query": args.query},
                headers={"Idempotency-Key": str(uuid4())},
            )
            response.raise_for_status()
            search_id = response.json()["search_id"]
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                progress = client.get(f"/collector/searches/{search_id}/progress")
                progress.raise_for_status()
                if not progress.json()["polling_required"]:
                    break
                time.sleep(2)
            response = client.get(f"/collector/searches/{search_id}/diagnostics")
            response.raise_for_status()
        folder = evidence_directory() / "experiments"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / (str(uuid4()) + ".json")
        with path.open("x") as handle:
            path.chmod(0o600)
            json.dump(response.json(), handle, ensure_ascii=False, indent=2)
        print("Search ID:", search_id, "Evidence:", path)


if __name__ == "__main__":
    main()
