from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

KNOWN_DOMAIN_PUBLISHERS = {
    "who.int": "World Health Organization",
    "www.who.int": "World Health Organization",
}

KNOWN_HOSTING_PLATFORMS = {
    "kaggle.com": "Kaggle",
    "www.kaggle.com": "Kaggle",
}


@dataclass(frozen=True)
class SourceIdentity:
    publisher: str = ""
    hosting_platform: str = ""
    uploader: str = ""


def identify_source(url: str) -> SourceIdentity:
    parsed_url = urlsplit(url)
    hostname = parsed_url.hostname or ""
    publisher = KNOWN_DOMAIN_PUBLISHERS.get(hostname, "")
    hosting_platform = KNOWN_HOSTING_PLATFORMS.get(hostname, "")
    uploader = _kaggle_uploader(parsed_url.path) if hosting_platform == "Kaggle" else ""

    return SourceIdentity(
        publisher=publisher,
        hosting_platform=hosting_platform,
        uploader=uploader,
    )


def _kaggle_uploader(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "datasets":
        return parts[1]
    return ""

