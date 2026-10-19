"""Resolve a public Dryad DOI, its selected version and complete file listing."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from collector.collection.connectors.metadata import (
    MetadataReader,
    api_link,
    file_resource,
    hal_link,
    known_resources,
)
from collector.collection.connectors.shared import positive_id, repository_origin, text
from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.extraction.extractor import html_to_text
from collector.storage.metadata import normalize_doi


class DryadConnector:
    name = "dryad"
    method = "dryad_api"
    api_root = "https://datadryad.org/api/v2"

    def supports(self, url):
        return self.api_url(url) is not None

    def _doi(self, url):
        if repository_origin(url, ("datadryad.org",)) is None:
            return ""
        parsed = urlsplit(url)
        if {"version", "id"} & parse_qs(parsed.query, keep_blank_values=True).keys():
            return ""
        match = re.fullmatch(
            r"/(?:stash/)?(?:dataset/)?doi:(10\.5061/dryad\.[^/]+?)/?", unquote(parsed.path)
        )
        return normalize_doi(match[1]) if match else ""

    def api_url(self, url):
        doi = self._doi(url)
        return self.api_root + "/datasets/" + quote("doi:" + doi, safe="") if doi else None

    def reference_identity(self, url):
        doi = self._doi(url)
        if not doi:
            raise ValueError("Unsupported Dryad reference")
        return RecordIdentity(self.name, "https://datadryad.org", "dataset", doi, doi)

    def fetch_metadata(self, url, fetch_json):
        reader = MetadataReader(self.api_root, fetch_json)
        dataset = reader.read(self.api_url(url))
        if normalize_doi(dataset.get("identifier")) != self._doi(url):
            raise ValueError("Dryad DOI mismatch")
        version_url = api_link(self.api_root, hal_link(dataset, "stash:version"))
        if not re.fullmatch(r"/api/v2/versions/[1-9][0-9]*", urlsplit(version_url).path):
            raise ValueError("Invalid Dryad version link")
        version = reader.read(version_url)
        if api_link(self.api_root, hal_link(version, "self")) != version_url or api_link(
            self.api_root, hal_link(version, "stash:dataset")
        ) != self.api_url(url):
            raise ValueError("Dryad version does not belong to requested dataset")
        files_url = api_link(self.api_root, hal_link(version, "stash:files"))
        if files_url != version_url + "/files":
            raise ValueError("Dryad file listing changed version scope")
        files = reader.listing(files_url, "stash:files")
        return reader.response({"dataset": dataset, "version": version, "files": files})

    def normalize(self, url, payload):
        if not self.supports(url) or not isinstance(payload, dict):
            raise ValueError("Invalid Dryad metadata")
        dataset, version, files = (payload.get(k) for k in ("dataset", "version", "files"))
        if (
            not isinstance(dataset, dict)
            or not isinstance(version, dict)
            or not isinstance(files, list)
            or len(files) > 10000
            or normalize_doi(dataset.get("identifier")) != self._doi(url)
        ):
            raise ValueError("Invalid Dryad record identity or file listing")
        version_url = api_link(self.api_root, hal_link(dataset, "stash:version"))
        if (
            not re.fullmatch(r"/api/v2/versions/[1-9][0-9]*", urlsplit(version_url).path)
            or api_link(self.api_root, hal_link(version, "self")) != version_url
            or api_link(self.api_root, hal_link(version, "stash:dataset")) != self.api_url(url)
        ):
            raise ValueError("Dryad version mismatch")
        version_id = version_url.rsplit("/", 1)[1]
        title = text(version.get("title"))
        if not title:
            raise ValueError("Missing Dryad title")
        resources, seen = [], set()
        for file in files:
            if not isinstance(file, dict):
                raise ValueError("Invalid Dryad file")
            self_url = api_link(self.api_root, hal_link(file, "self"))
            match = re.fullmatch(r"/api/v2/files/([1-9][0-9]*)", urlsplit(self_url).path)
            if (
                match is None
                or self_url in seen
                or api_link(self.api_root, hal_link(file, "stash:version")) != version_url
            ):
                raise ValueError("Dryad file identity or version mismatch")
            download = api_link(self.api_root, hal_link(file, "stash:download"))
            if download != self_url + "/download":
                raise ValueError("Invalid Dryad download link")
            seen.add(self_url)
            resources.append(
                file_resource(
                    text(file.get("path")),
                    download,
                    key=f"dryad:{version_id}:file:{match[1]}",
                    mime=text(file.get("mimeType")),
                    size=file.get("size"),
                    restricted=dataset.get("visibility") != "public",
                )
            )
        doi = self._doi(url)
        return NormalizedRecord(
            identity=RecordIdentity(
                self.name,
                "https://datadryad.org",
                "dataset",
                doi,
                doi,
                positive_id(version.get("versionNumber")) or version_id,
            ),
            landing_url=url,
            metadata_source_url=self.api_url(url),
            title=title,
            description=html_to_text(text(version.get("abstract"))),
            publisher="Dryad",
            publication_date=text(version.get("publicationDate") or dataset.get("publicationDate")),
            license=text(version.get("license") or dataset.get("license")),
            doi=doi,
            resources=tuple(resources),
        )

    def scope_resources(self, url, resources, known_record=None):
        return known_resources(resources, known_record)
