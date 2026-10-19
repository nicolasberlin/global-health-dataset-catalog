from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = LAB_ROOT / "data" / "evidence"


def evidence_directory() -> Path:
    """Use the same laboratory storage root for snapshots and CLI scenarios."""
    return Path(os.getenv("LAB_EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR))).resolve()


def local_api_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("The laboratory API target must be a loopback HTTP origin.")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_base: str
    evidence_dir: Path

    @classmethod
    def configured(cls):
        database = os.getenv("LAB_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not database:
            raise RuntimeError(
                "Set DATABASE_URL or LAB_DATABASE_URL before starting the laboratory."
            )
        return cls(
            database,
            local_api_url(os.getenv("LAB_API_BASE_URL", "http://127.0.0.1:8001")),
            evidence_directory(),
        )
