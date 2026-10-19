"""Public InvenioRDM records on explicitly configured instances."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, urlsplit

from collector.collection.connectors.metadata import (
    MetadataReader,
    api_link,
    file_resource,
    known_resources,
)
from collector.collection.connectors.shared import positive_id, repository_origin, text
from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.extraction.extractor import html_to_text
from collector.storage.metadata import normalize_doi

RECORD_PATH = re.compile(r"^/records?/([a-zA-Z0-9][a-zA-Z0-9_-]{0,127})/?$")


class InvenioRDMConnector:
    name = "inveniordm"
    method = "inveniordm_api"

    def __init__(self, hosts=()):
        self.hosts = hosts

    def supports(self, url):
        return self.api_url(url) is not None

    def api_url(self, url):
        origin = repository_origin(url, self.hosts)
        parsed = urlsplit(url)
        match = RECORD_PATH.fullmatch(parsed.path)
        if (
            not origin
            or match is None
            or "version" in parse_qs(parsed.query, keep_blank_values=True)
        ):
            return None
        return f"{origin}/api/records/{match[1]}"

    def reference_identity(self, url):
        api = self.api_url(url)
        if not api:
            raise ValueError("Unsupported InvenioRDM reference")
        return RecordIdentity(
            self.name, repository_origin(url, self.hosts), "dataset", api.rsplit("/", 1)[1]
        )

    def fetch_metadata(self, url, fetch_json):
        api = self.api_url(url)
        reader = MetadataReader(api.rsplit("/records/", 1)[0], fetch_json)
        record = reader.read(api)
        self._validate_record(url, record)
        files = record.get("files")
        if not isinstance(files, dict) or type(files.get("enabled")) is not bool:
            raise ValueError("Missing InvenioRDM file state")
        if not files["enabled"]:
            listing = {"entries": []}
        else:
            # Record responses may embed summaries without transfer status or
            # content links. The dedicated endpoint is authoritative.
            listing = reader.read(api + "/files")
        return reader.response({"record": record, "files": listing})

    def _validate_record(self, url, record):
        api = self.api_url(url)
        if (
            not api
            or not isinstance(record, dict)
            or str(record.get("id")) != api.rsplit("/", 1)[1]
            or record.get("is_published") is not True
        ):
            raise ValueError("InvenioRDM published record identity mismatch")

    def normalize(self, url, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid InvenioRDM metadata")
        record, files = payload.get("record"), payload.get("files")
        self._validate_record(url, record)
        metadata = record.get("metadata")
        if not isinstance(metadata, dict) or not text(metadata.get("title")):
            raise ValueError("Missing InvenioRDM metadata")
        entries = files.get("entries") if isinstance(files, dict) else None
        if isinstance(entries, dict):
            if any(
                not isinstance(item, dict) or item.get("key") != key
                for key, item in entries.items()
            ):
                raise ValueError("InvenioRDM file key mismatch")
            entries = list(entries.values())
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError("Missing InvenioRDM file listing")
        api = self.api_url(url)
        root = api.rsplit("/records/", 1)[0]
        access = record.get("access", {})
        restricted = access.get("files") != "public" if isinstance(access, dict) else True
        resources, seen = [], set()
        for file in entries:
            if not isinstance(file, dict):
                raise ValueError("Invalid InvenioRDM file")
            key = text(file.get("key"))
            links = file.get("links", {})
            download = api_link(root, links.get("content", "") if isinstance(links, dict) else "")
            if (
                not key
                or key in seen
                or file.get("status") != "completed"
                or download != api + "/files/" + quote(key, safe="") + "/content"
            ):
                raise ValueError("InvenioRDM file identity or scope mismatch")
            seen.add(key)
            file_access = file.get("access", {})
            hidden = isinstance(file_access, dict) and file_access.get("hidden") is True
            resources.append(
                file_resource(
                    key,
                    download,
                    key=f"inveniordm:{urlsplit(api).hostname}:{record['id']}:file:{key}",
                    mime=text(file.get("mimetype")),
                    size=file.get("size"),
                    restricted=restricted or hidden,
                )
            )
        pids = record.get("pids", {})
        doi_info = pids.get("doi", {}) if isinstance(pids, dict) else {}
        doi = normalize_doi(doi_info.get("identifier")) if isinstance(doi_info, dict) else ""
        versions = record.get("versions", {})
        version = positive_id(versions.get("index")) if isinstance(versions, dict) else ""
        rights = metadata.get("rights", [])
        license_name = (
            text(rights[0].get("id"))
            if isinstance(rights, list) and rights and isinstance(rights[0], dict)
            else ""
        )
        identity = self.reference_identity(url)
        return NormalizedRecord(
            identity=RecordIdentity(
                self.name, identity.repository_origin, "dataset", identity.native_id, doi, version
            ),
            landing_url=url,
            metadata_source_url=api,
            title=text(metadata.get("title")),
            description=html_to_text(text(metadata.get("description"))),
            publisher=text(metadata.get("publisher")),
            publication_date=text(metadata.get("publication_date")),
            license=license_name,
            doi=doi,
            resources=tuple(resources),
        )

    def scope_resources(self, url, resources, known_record=None):
        return known_resources(resources, known_record)
