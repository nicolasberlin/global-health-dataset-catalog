"""DSpace 7+ public items and ORIGINAL bundle bitstreams via configured REST APIs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from collector.collection.connectors.metadata import (
    MetadataReader,
    api_link,
    file_resource,
    hal_link,
    known_resources,
)
from collector.collection.connectors.shared import repository_origin, text
from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.extraction.extractor import html_to_text
from collector.storage.metadata import normalize_doi

ITEM_PATH = re.compile(r"^/(?:items|entities/[a-zA-Z_-]+)/([a-fA-F0-9-]{36})/?$")


def uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return ""


def metadata_values(metadata, key):
    values = metadata.get(key, [])
    return (
        [text(item.get("value")) for item in values if isinstance(item, dict)]
        if (isinstance(values, list))
        else []
    )


class DSpaceConnector:
    name = "dspace"
    method = "dspace_api"

    def __init__(self, api_bases=()):
        self.api_bases = dict(api_bases)
        for base in self.api_bases.values():
            parsed = urlsplit(base)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.port not in {None, 443}
            ):
                raise ValueError("DSpace API bases must be credential-free HTTPS URLs")

    def supports(self, url):
        return self.api_url(url) is not None

    def api_url(self, url):
        if repository_origin(url, tuple(self.api_bases)) is None:
            return None
        parsed = urlsplit(url)
        match = ITEM_PATH.fullmatch(parsed.path)
        if match is None or "version" in parse_qs(parsed.query, keep_blank_values=True):
            return None
        identifier = uuid(match[1])
        return (
            self.api_bases[parsed.hostname].rstrip("/") + "/core/items/" + identifier
            if identifier
            else None
        )

    def reference_identity(self, url):
        api = self.api_url(url)
        if not api:
            raise ValueError("Unsupported DSpace item reference")
        return RecordIdentity(
            self.name,
            self.api_bases[urlsplit(url).hostname].rstrip("/"),
            "dataset",
            api.rsplit("/", 1)[1],
        )

    def _validate_item(self, url, item):
        expected = self.reference_identity(url).native_id
        if (
            not isinstance(item, dict)
            or uuid(item.get("uuid")) != expected
            or item.get("type") != "item"
            or item.get("inArchive") is not True
            or item.get("withdrawn") is not False
        ):
            raise ValueError("DSpace published item identity mismatch")

    def fetch_metadata(self, url, fetch_json):
        api = self.api_url(url)
        root = self.api_bases[urlsplit(url).hostname].rstrip("/")
        reader = MetadataReader(root, fetch_json)
        item = reader.read(api)
        self._validate_item(url, item)
        bundles_url = api_link(root, hal_link(item, "bundles"))
        if bundles_url != api + "/bundles":
            raise ValueError("DSpace bundle link changed item scope")
        bundles = reader.listing(bundles_url, "bundles")
        files, seen = [], set()
        for bundle in bundles:
            if not isinstance(bundle, dict) or not uuid(bundle.get("uuid")):
                raise ValueError("Invalid DSpace bundle")
            identifier = uuid(bundle["uuid"])
            if identifier in seen:
                raise ValueError("Duplicate DSpace bundle")
            seen.add(identifier)
            if bundle.get("name") != "ORIGINAL":
                continue  # Exclude thumbnails, extracted text and license artifacts.
            listing_url = api_link(root, hal_link(bundle, "bitstreams"))
            if listing_url != root + f"/core/bundles/{identifier}/bitstreams":
                raise ValueError("DSpace bitstream link changed bundle scope")
            files.extend(reader.listing(listing_url, "bitstreams"))
            if len(files) > 10000:
                raise ValueError("DSpace file listing is too large")
        return reader.response({"item": item, "files": files})

    def normalize(self, url, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid DSpace metadata")
        item, files = payload.get("item"), payload.get("files")
        self._validate_item(url, item)
        if not isinstance(files, list) or len(files) > 10000:
            raise ValueError("Missing DSpace file listing")
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Missing DSpace metadata")
        titles = metadata_values(metadata, "dc.title")
        if not titles or not titles[0]:
            raise ValueError("Missing DSpace title")
        identity = self.reference_identity(url)
        root = identity.repository_origin
        resources, seen = [], set()
        for file in files:
            identifier = uuid(file.get("uuid")) if isinstance(file, dict) else ""
            if not identifier or identifier in seen or file.get("type") != "bitstream":
                raise ValueError("Invalid or duplicate DSpace bitstream")
            seen.add(identifier)
            download = api_link(root, hal_link(file, "content"))
            if download != root + f"/core/bitstreams/{identifier}/content":
                raise ValueError("DSpace content link does not match bitstream")
            resources.append(
                file_resource(
                    text(file.get("name")),
                    download,
                    key=f"dspace:{urlsplit(root).hostname}:{identity.native_id}:file:{identifier}",
                    size=file.get("sizeBytes"),
                )
            )
        identifiers = metadata_values(metadata, "dc.identifier.doi") + metadata_values(
            metadata, "dc.identifier.uri"
        )
        doi = next((normalize_doi(value) for value in identifiers if normalize_doi(value)), "")
        descriptions = metadata_values(metadata, "dc.description.abstract") or metadata_values(
            metadata, "dc.description"
        )
        dates = metadata_values(metadata, "dc.date.issued")
        publishers = metadata_values(metadata, "dc.publisher")
        licenses = metadata_values(metadata, "dc.rights.uri") or metadata_values(
            metadata, "dc.rights"
        )
        return NormalizedRecord(
            identity=RecordIdentity(self.name, root, "dataset", identity.native_id, doi),
            landing_url=url,
            metadata_source_url=self.api_url(url),
            title=titles[0],
            description=html_to_text("\n".join(descriptions)),
            publisher=publishers[0] if publishers else "",
            publication_date=dates[0] if dates else "",
            license=licenses[0] if licenses else "",
            doi=doi,
            resources=tuple(resources),
        )

    def scope_resources(self, url, resources, known_record=None):
        return known_resources(resources, known_record)
