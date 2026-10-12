"""Resolve one Dataverse dataset or file without broadening its scope."""

from __future__ import annotations

from urllib.parse import parse_qs, quote, urlencode, urlsplit

from collector.collection.connectors.shared import positive_id, repository_origin, text
from collector.collection.records import NormalizedRecord, RecordIdentity
from collector.extraction.distributions import guess_format
from collector.storage.metadata import normalize_doi
from collector.storage.models import DistributionCandidate


class DataverseConnector:
    name = "dataverse"
    method = "dataverse_api"

    def __init__(self, hosts: tuple[str, ...]):
        self.hosts = hosts

    def supports(self, url: str) -> bool:
        if repository_origin(url, self.hosts) is None:
            return False
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            return False
        persistent = query.get("persistentId", [""])[0]
        if parsed.path == "/file.xhtml":
            return bool(persistent or positive_id(query.get("fileId", [""])[0]))
        return parsed.path in {"/dataset.xhtml", "/citation"} and bool(persistent)

    def api_url(self, url: str) -> str | None:
        if not self.supports(url):
            return None
        origin = repository_origin(url, self.hosts)
        if origin is None:
            return None
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            return None
        persistent = query.get("persistentId", [""])[0]
        file_id = positive_id(query.get("fileId", [""])[0])
        if parsed.path == "/file.xhtml":
            version = query.get("version", [""])[0]
            suffix = (
                "/versions/" + quote(version, safe="")
                if version and version.upper() not in {"LATEST", ":LATEST", ":LATEST-PUBLISHED"}
                else ""
            )
            if file_id:
                return f"{origin}/api/v1/files/{file_id}{suffix}"
            if persistent:
                return origin + "/api/v1/files/:persistentId" + suffix + "?" + urlencode(
                    {"persistentId": persistent}
                )
        if parsed.path in {"/dataset.xhtml", "/citation"} and persistent:
            version = query.get("version", [""])[0]
            if version and version.upper() not in {"LATEST", ":LATEST", ":LATEST-PUBLISHED"}:
                return None  # HTML retains explicitly pinned version scope.
            return origin + "/api/v1/datasets/:persistentId/?" + urlencode(
                {"persistentId": persistent}
            )
        return None

    def normalize(self, url: str, payload: dict | list) -> NormalizedRecord:
        api_url = self.api_url(url)
        if api_url is None:
            raise ValueError("Unsupported Dataverse record URL")
        is_file = urlsplit(url).path == "/file.xhtml"
        if isinstance(payload, dict) and payload.get("status") == "OK":
            data = payload.get("data")
        elif is_file and isinstance(payload, list):
            data = payload
        else:
            raise ValueError("Invalid Dataverse metadata response")
        if is_file and isinstance(data, list):
            if len(data) != 1:
                raise ValueError("Ambiguous Dataverse file metadata")
            data = data[0]
        if not isinstance(data, dict):
            raise ValueError("Invalid Dataverse record")
        version = {} if is_file else data.get("latestVersion")
        if not isinstance(version, dict):
            raise ValueError("Invalid Dataverse version")
        records = [data] if is_file else version.get("files")
        if not isinstance(records, list) or len(records) > 10000:
            raise ValueError("Invalid Dataverse file listing")
        query = parse_qs(urlsplit(url).query)
        requested_pid = query.get("persistentId", [""])[0]
        requested_id = positive_id(query.get("fileId", [""])[0]) if is_file else ""
        origin = f"https://{urlsplit(url).hostname}"
        resources = []
        file_pid = ""
        file_native_id = ""
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid Dataverse file record")
            file = record.get("dataFile")
            if file is None and "filename" in record:
                file = record
            if not isinstance(file, dict):
                raise ValueError("Missing Dataverse dataFile representation")
            identifier = positive_id(file.get("id"))
            if not identifier:
                raise ValueError("Invalid Dataverse dataFile identifier")
            if is_file and requested_id and identifier != requested_id:
                raise ValueError("Dataverse file identity mismatch")
            file_pid = text(file.get("persistentId"))
            if is_file and requested_pid and file_pid and file_pid != requested_pid:
                raise ValueError("Dataverse persistent identity mismatch")
            filename = text(file.get("filename")) or text(record.get("label"))
            mime = text(file.get("contentType"))
            fmt, ext = guess_format(filename, mime_type=mime)
            resources.append(DistributionCandidate(
                url=f"{origin}/api/access/datafile/{identifier}",
                format=fmt, probability=1.0, extension=ext, anchor=filename, mime_type=mime,
                signals={
                    "resource_key": f"dataverse:{urlsplit(url).hostname}:file:{identifier}",
                    "restricted": record.get("restricted", file.get("restricted", False)) is True,
                },
            ))
            file_native_id = identifier
        blocks = version.get("metadataBlocks") or {}
        citation = blocks.get("citation", {}) if isinstance(blocks, dict) else {}
        fields = citation.get("fields", []) if isinstance(citation, dict) else []
        metadata = {
            field["typeName"]: field.get("value")
            for field in fields
            if isinstance(field, dict) and isinstance(field.get("typeName"), str)
        } if isinstance(fields, list) else {}
        description = metadata.get("dsDescription", [])
        descriptions = [
            text(item["dsDescriptionValue"].get("value"))
            for item in description
            if isinstance(item, dict) and isinstance(item.get("dsDescriptionValue"), dict)
        ] if isinstance(description, list) else []
        persistent = (file_pid or requested_pid) if is_file else text(data.get("persistentId"))
        if not persistent and not is_file:
            persistent = requested_pid
        if not is_file and requested_pid and persistent != requested_pid:
            raise ValueError("Dataverse dataset identity mismatch")
        version_id = ""
        if is_file:
            requested_version = query.get("version", [""])[0]
            if requested_version.upper() not in {"LATEST", ":LATEST", ":LATEST-PUBLISHED"}:
                version_id = requested_version
        if not is_file and isinstance(version.get("versionNumber"), int):
            minor = version.get("versionMinorNumber", 0)
            if isinstance(minor, int):
                version_id = f"{version['versionNumber']}.{minor}"
        license_info = version.get("license")
        file_info = data.get("dataFile", data) if is_file else {}
        return NormalizedRecord(
            identity=RecordIdentity(
                platform=self.name, repository_origin=origin,
                kind="file" if is_file else "dataset",
                native_id=file_native_id if is_file else positive_id(data.get("id")),
                persistent_id=persistent, version=version_id,
            ),
            landing_url=url, metadata_source_url=api_url,
            title=text(metadata.get("title")) or (resources[0].anchor if resources else ""),
            description=(text(data.get("description")) or text(file_info.get("description")))
            if is_file else " ".join(descriptions),
            publisher=text(metadata.get("publisher")),
            publication_date=text(version.get("releaseTime")) or text(data.get("publicationDate")),
            license=text(license_info.get("name")) if isinstance(license_info, dict) else "",
            doi=normalize_doi(persistent), resources=tuple(resources),
        )

    def reference_identity(self, url: str) -> RecordIdentity:
        if not self.supports(url):
            raise ValueError("Unsupported Dataverse reference")
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        is_file = parsed.path == "/file.xhtml"
        requested_version = query.get("version", [""])[0]
        if requested_version.upper() in {"LATEST", ":LATEST", ":LATEST-PUBLISHED"}:
            requested_version = ""
        return RecordIdentity(
            platform=self.name, repository_origin=f"https://{parsed.hostname}",
            kind="file" if is_file else "dataset",
            native_id=positive_id(query.get("fileId", [""])[0]) if is_file else "",
            persistent_id=query.get("persistentId", [""])[0],
            version=requested_version,
        )

    def scope_resources(
        self, url: str, resources: list[DistributionCandidate],
        known_record: NormalizedRecord | None = None,
    ) -> list[DistributionCandidate]:
        if urlsplit(url).path != "/file.xhtml":
            return resources
        query = parse_qs(urlsplit(url).query)
        identifier = positive_id(query.get("fileId", [""])[0])
        persistent = query.get("persistentId", [""])[0]
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
            resource_pid = parse_qs(parsed.query).get("persistentId", [""])[0]
            if (
                (identifier and parsed.path == f"/api/access/datafile/{identifier}")
                or (persistent and parsed.path == "/api/access/datafile/:persistentId"
                    and resource_pid == persistent)
            ):
                retained.append(resource)
        return retained

