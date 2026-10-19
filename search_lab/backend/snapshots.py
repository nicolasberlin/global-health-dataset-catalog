"""Append-only evidence outside the removable tool directory."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


def checksum(document):
    payload = {key: value for key, value in document.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def candidate_observation(observation, candidate_id):
    trace = observation["trace"]
    candidate = next(
        (
            item
            for item in trace["summary"].get("items", [])
            if str(item.get("candidate_id")) == str(candidate_id)
        ),
        None,
    )
    if candidate is None:
        raise ValueError("Candidate not found in this search.")
    job_id = ((candidate.get("automatic_collection") or {}).get("job") or {}).get("id")
    scoped_trace = {
        key: copy.deepcopy(trace[key])
        for key in ("schema_version", "document_type", "exported_at", "context", "export")
        if key in trace
    }
    scoped_trace["summary"] = {"items": [copy.deepcopy(candidate)]}
    scoped_trace["collections"] = [
        copy.deepcopy(item)
        for item in trace.get("collections", [])
        if item and job_id is not None and item.get("job_id") == job_id
    ]
    scoped_trace["repository_classifications"] = [
        copy.deepcopy(item)
        for item in trace.get("repository_classifications", [])
        if str(item.get("candidate_id")) == str(candidate_id)
    ]
    return {
        "trace": scoped_trace,
        "attempts": [
            copy.deepcopy(item)
            for item in observation.get("attempts", [])
            if job_id is not None and item.get("job_id") == job_id
        ],
        "warning": "Selected candidate only. Current state and dated historical traces.",
    }, {"id": str(candidate_id), "title": candidate["title"], "url": candidate["url"]}


class Snapshots:
    def __init__(self, directory):
        self.directory = Path(directory)

    def owner_directory(self, owner_id):
        return self.directory / hashlib.sha256(owner_id.encode()).hexdigest()

    def create(self, owner_id, observation, notes, candidate_id=None):
        candidate = None
        if candidate_id is not None:
            observation, candidate = candidate_observation(observation, candidate_id)
        document = {
            "schema_version": "1.1" if candidate else "1.0",
            "scope": "candidate" if candidate else "search",
            "candidate": candidate,
            "document_type": "search_lab_snapshot",
            "id": str(uuid4()),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "collector_version": None,
            "evidence_scope": (
                "State observed at capture time; not the original historical outcome."
            ),
            "notes": notes,
            "observation": observation,
        }
        document["sha256"] = checksum(document)
        body = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        directory = self.owner_directory(owner_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (document["id"] + ".json")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return document

    def read(self, owner_id, identifier):
        # Route parameters are UUIDs; do not accept arbitrary filenames.
        path = self.owner_directory(owner_id) / (str(UUID(str(identifier))) + ".json")
        document = json.loads(path.read_text())
        if document.get("sha256") != checksum(document):
            raise ValueError("Snapshot was modified after capture.")
        return document

    def list(self, owner_id):
        directory = self.owner_directory(owner_id)
        items = []
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[
            :200
        ]:
            try:
                document = self.read(owner_id, path.stem)
                context = document["observation"]["trace"]["context"]
                items.append(
                    {
                        "id": document["id"],
                        "captured_at": document["captured_at"],
                        "search_id": context["search_id"],
                        "query": context["query"],
                        "label": document["notes"].get("label", ""),
                        "scope": document.get("scope", "search"),
                        "candidate": document.get("candidate"),
                    }
                )
            except (OSError, ValueError, KeyError):
                continue
        return items
