"""Resolve a published Zenodo record or exactly one of its files."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

from collector.collection.connectors.shared import positive_id, repository_origin, text
from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.extraction.distributions import guess_format
from collector.extraction.extractor import html_to_text
from collector.storage.metadata import normalize_doi
from collector.storage.models import DistributionCandidate
from collector.url_utils import normalize_http_url

RECORD_PATH = re.compile(r"^/records?/([1-9][0-9]*)(?:/files/(.+))?/?$")


class ZenodoConnector:
    name = "zenodo"
    method = "zenodo_api"

    def __init__(self, hosts: tuple[str, ...] = ("zenodo.org",)):
        self.hosts = hosts

    def supports(self, url: str) -> bool:
        return self.api_url(url) is not None

    def api_url(self, url: str) -> str | None:
        origin = repository_origin(url, self.hosts)
        match = RECORD_PATH.fullmatch(urlsplit(url).path) if origin else None
        if match is None:
            return None
        if "version" in parse_qs(urlsplit(url).query, keep_blank_values=True):
            return None
        return f"{origin}/api/records/{match[1]}"

    def normalize(self, url: str, payload: dict | list) -> NormalizedRecord:
        api_url = self.api_url(url)
        if api_url is None or not isinstance(payload, dict):
            raise ValueError("Invalid Zenodo response")
        match = RECORD_PATH.fullmatch(urlsplit(url).path)
        identifier = positive_id(payload.get("id"))
        if not identifier or identifier != match[1]:
            raise ValueError("Zenodo record identity mismatch")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or not text(metadata.get("title")):
            raise ValueError("Invalid Zenodo metadata")
        files = payload.get("files")
        if not isinstance(files, list) or len(files) > 10000:
            raise ValueError("Invalid Zenodo file listing")
        selected_filename = unquote(match[2].rstrip("/")) if match[2] else ""
        resources = []
        filenames = set()
        for file in files:
            if not isinstance(file, dict):
                raise ValueError("Invalid Zenodo file record")
            filename = text(file.get("key")) or text(file.get("filename"))
            links = file.get("links")
            if not filename or filename in filenames or not isinstance(links, dict):
                raise ValueError("Invalid or ambiguous Zenodo file")
            filenames.add(filename)
            download_url = text(links.get("content")) or text(links.get("self"))
            if normalize_http_url(download_url) is None:
                raise ValueError("Missing Zenodo download link")
            if selected_filename and filename != selected_filename:
                continue
            mime = text(file.get("mimetype")) or text(file.get("type"))
            fmt, ext = guess_format(filename, mime_type=mime)
            resources.append(DistributionCandidate(
                url=download_url, format=fmt, probability=1.0,
                extension=ext, anchor=filename, mime_type=mime,
                signals={
                    "resource_key": f"zenodo:{urlsplit(url).hostname}:{identifier}:file:{filename}",
                    "restricted": metadata.get("access_right")
                    in ("restricted", "closed", "embargoed"),
                    "size_bytes": file.get("size"),
                },
            ))
        if selected_filename and not resources:
            raise ValueError("Requested Zenodo file is missing")
        origin = f"https://{urlsplit(url).hostname}"
        doi = normalize_doi(payload.get("doi") or metadata.get("doi"))
        license_info = metadata.get("license")
        license_name = text(license_info.get("id")) if isinstance(license_info, dict) else text(
            license_info
        )
        return NormalizedRecord(
            identity=RecordIdentity(
                platform=self.name, repository_origin=origin,
                kind="file" if selected_filename else "dataset",
                native_id=(f"{identifier}/files/{selected_filename}"
                           if selected_filename else identifier),
                persistent_id="" if selected_filename else doi,
                version=text(metadata.get("version")),
            ),
            landing_url=url, metadata_source_url=api_url,
            title=selected_filename or text(metadata.get("title")),
            description=html_to_text(text(metadata.get("description"))),
            publisher=text(metadata.get("publisher")),
            publication_date=text(metadata.get("publication_date")),
            license=license_name, doi="" if selected_filename else doi,
            resources=tuple(resources), parent_persistent_id=doi if selected_filename else "",
        )

    def scope_resources(
        self, url: str, resources: list[DistributionCandidate],
        known_record: NormalizedRecord | None = None,
    ) -> list[DistributionCandidate]:
        match = RECORD_PATH.fullmatch(urlsplit(url).path)
        if match is None or not match[2]:
            return resources
        filename = unquote(match[2].rstrip("/"))
        known_urls = ({resource.url for resource in known_record.resources}
                      if known_record else set())
        retained = []
        for resource in resources:
            if resource.url in known_urls:
                retained.append(resource)
                continue
            parsed = urlsplit(resource.url)
            if parsed.hostname != urlsplit(url).hostname:
                continue
            path = unquote(parsed.path)
            if path in {
                f"/records/{match[1]}/files/{filename}",
                f"/record/{match[1]}/files/{filename}",
                f"/api/records/{match[1]}/files/{filename}/content",
            }:
                retained.append(resource)
        return retained

    def reference_identity(self, url: str) -> RecordIdentity:
        if not self.supports(url):
            raise ValueError("Unsupported Zenodo reference")
        parsed = urlsplit(url)
        match = RECORD_PATH.fullmatch(parsed.path)
        filename = unquote(match[2].rstrip("/")) if match[2] else ""
        return RecordIdentity(
            platform=self.name, repository_origin=f"https://{parsed.hostname}",
            kind="file" if filename else "dataset",
            native_id=f"{match[1]}/files/{filename}" if filename else match[1],
        )

