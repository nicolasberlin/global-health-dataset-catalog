"""Resolve public Figshare articles through the API, preserving pinned versions."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from collector.collection.connectors.shared import positive_id, repository_origin, text
from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.extraction.distributions import guess_format
from collector.extraction.extractor import html_to_text
from collector.storage.metadata import normalize_doi
from collector.storage.models import DistributionCandidate
from collector.url_utils import normalize_http_url

ARTICLE_PATH = re.compile(
    r"^/articles/(?:[a-z_]+/[^/]+/)?([1-9][0-9]*)(?:/([1-9][0-9]*))?/?$"
)
API_ORIGIN = "https://api.figshare.com"


class FigshareConnector:
    name = "figshare"
    method = "figshare_api"

    def __init__(self, hosts: tuple[str, ...] = ("figshare.com", "springernature.figshare.com")):
        self.hosts = hosts

    def supports(self, url: str) -> bool:
        return self.api_url(url) is not None

    def api_url(self, url: str) -> str | None:
        if repository_origin(url, self.hosts) is None:
            return None
        parsed = urlsplit(url)
        match = ARTICLE_PATH.fullmatch(parsed.path)
        if match is None or "version" in parse_qs(parsed.query, keep_blank_values=True):
            return None
        suffix = f"/versions/{match[2]}" if match[2] else ""
        return f"{API_ORIGIN}/v2/articles/{match[1]}{suffix}"

    def reference_identity(self, url: str) -> RecordIdentity:
        if not self.supports(url):
            raise ValueError("Unsupported Figshare reference")
        match = ARTICLE_PATH.fullmatch(urlsplit(url).path)
        return RecordIdentity(
            platform=self.name, repository_origin=API_ORIGIN, kind="dataset",
            native_id=match[1], version=match[2] or "",
        )

    def normalize(self, url: str, payload: dict | list) -> NormalizedRecord:
        api_url = self.api_url(url)
        if api_url is None or not isinstance(payload, dict):
            raise ValueError("Invalid Figshare response")
        match = ARTICLE_PATH.fullmatch(urlsplit(url).path)
        identifier, version = positive_id(payload.get("id")), positive_id(payload.get("version"))
        if identifier != match[1] or not version or (match[2] and version != match[2]):
            raise ValueError("Figshare record identity or version mismatch")
        if not text(payload.get("title")):
            raise ValueError("Missing Figshare title")
        files = payload.get("files")
        if not isinstance(files, list) or len(files) > 10000:
            raise ValueError("Invalid Figshare file listing")
        resources, file_ids = [], set()
        for file in files:
            if not isinstance(file, dict):
                raise ValueError("Invalid Figshare file record")
            file_id, filename = positive_id(file.get("id")), text(file.get("name"))
            download_url = text(file.get("download_url"))
            if (not file_id or file_id in file_ids or not filename
                    or normalize_http_url(download_url) is None):
                raise ValueError("Invalid or ambiguous Figshare file")
            file_ids.add(file_id)
            mime = text(file.get("mimetype"))
            fmt, ext = guess_format(filename, mime_type=mime)
            resources.append(DistributionCandidate(
                url=download_url, format=fmt, probability=1.0,
                extension=ext, anchor=filename, mime_type=mime,
                signals={
                    "resource_key": f"figshare:{identifier}:version:{version}:file:{file_id}",
                    "restricted": payload.get("is_embargoed") is True,
                    "size_bytes": file.get("size"),
                },
            ))
        license_info = payload.get("license")
        license_name = text(license_info.get("name")) if isinstance(license_info, dict) else ""
        doi = normalize_doi(payload.get("doi"))
        return NormalizedRecord(
            identity=RecordIdentity(
                platform=self.name, repository_origin=API_ORIGIN, kind="dataset",
                native_id=identifier, persistent_id=doi, version=version,
            ),
            landing_url=url, metadata_source_url=api_url,
            title=text(payload.get("title")),
            description=html_to_text(text(payload.get("description"))),
            publisher=text(payload.get("publisher")),
            publication_date=text(payload.get("published_date")),
            license=license_name, doi=doi, resources=tuple(resources),
        )

    def scope_resources(
        self, url: str, resources: list[DistributionCandidate],
        known_record: NormalizedRecord | None = None,
    ) -> list[DistributionCandidate]:
        if known_record is not None:
            allowed = {item.url for item in known_record.resources}
            return [item for item in resources if item.url in allowed]
        match = ARTICLE_PATH.fullmatch(urlsplit(url).path)
        # An HTML fallback cannot prove which version owns a global download ID.
        return [] if match and match[2] else resources
