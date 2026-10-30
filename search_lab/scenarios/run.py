"""Explicit reproductions using production modules, with no catalog persistence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from collector.budget import collection_budget
from collector.collection.browser import configured_browser
from collector.collection.contracts import StrategyResult, public_url
from collector.collection.failures import CollectionStepError
from collector.collection.http import fetch_record_json
from collector.collection.orchestrator import collect_record
from collector.collection.pipeline import eligible_resources
from collector.collection.registry import default_registry
from collector.config import DEFAULT_CONFIG
from collector.diagnostics import PipelineFailure
from collector.discovery.adapters.shared import DiscoveredPage
from collector.network.fetch import PageFetchError, fetch_public_html
from collector.validation.downloads import page_access_diagnostic
from search_lab.backend.settings import ROOT, evidence_directory


def fingerprint():
    digest = hashlib.sha256()
    for directory in ("collector", "backend/app", "browser"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix not in {".py", ".cjs"} or "node_modules" in path.parts:
                continue
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "collector", "backend/app", "browser"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {"git_commit": revision, "modified": bool(dirty), "source_sha256": digest.hexdigest()}


def public_evidence(value):
    if isinstance(value, list):
        return [public_evidence(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.endswith("url") and isinstance(item, str):
                result[key] = public_url(item)
            elif key == "error" and item:
                result[key] = "Internal exception detail omitted."
            else:
                result[key] = public_evidence(item)
        return result
    return value


def execute(mode, url, *, offline_json=None, include_ai=False):
    selection = default_registry(DEFAULT_CONFIG).select(url)
    if mode == "api":
        if selection is None or selection.api_url is None:
            return {"code": "unsupported_record", "status": "not_run"}
        status = None
        try:
            if offline_json:
                payload = json.loads(Path(offline_json).read_text())
            else:
                hydrate = getattr(selection.connector, "fetch_metadata", None)
                response = hydrate(url, fetch_record_json) if hydrate else fetch_record_json(
                    selection.api_url
                )
                status, payload = response.http_status, response.payload
            record = selection.connector.normalize(url, payload)
        except ValueError:
            return {
                "status": "failed",
                "code": "repository_metadata_invalid",
                "failure_phase": "normalize",
                "http_status": status,
            }
        return {
            "status": "succeeded",
            "http_status": status,
            "metadata_url": public_url(selection.api_url),
            "identity": record.identity.to_dict(),
            "resources": [
                {"url": public_url(item.url), "format": item.format} for item in record.resources
            ],
            "limitation": "Metadata resolution only; resources were not validated.",
        }
    if offline_json:
        raise ValueError("Offline JSON is only supported for the API scenario.")
    if mode == "html":
        page = fetch_public_html(url)
        resolved = StrategyResult(DiscoveredPage(page.final_url, "html"), html=page.html)
        barrier = page_access_diagnostic(page.html)
        return {
            "status": "blocked" if barrier else "observed",
            "http_status": page.status_code,
            "code": barrier.code if barrier else "",
            "final_url": public_url(page.final_url),
            "links_found": len(eligible_resources(resolved)),
            "limitation": "HTML observation only; no AI calls or resource validation.",
        }
    with configured_browser(DEFAULT_CONFIG, url) as browser:
        if mode == "browser":
            if browser is None:
                return {"status": "not_run", "code": "browser_unavailable"}
            resolved = browser.render(url, metadata_url=selection.api_url if selection else None)
            barrier = page_access_diagnostic(resolved.html) if resolved.html else None
            return {
                "status": "blocked" if barrier else "observed",
                "http_status": resolved.http_status,
                "code": barrier.code if barrier else "",
                "metadata_code": resolved.metadata_code,
                "metadata_http_status": resolved.metadata_http_status,
                "links_found": len(eligible_resources(resolved)),
                "limitation": "Rendering only; no AI calls or catalog persistence.",
            }
        if not include_ai:
            raise ValueError("Collection requires --include-ai to authorize model calls.")
        from collector.classification.factory import build_default_page_classifier

        result = collect_record(
            url, DEFAULT_CONFIG, browser=browser, classifier=build_default_page_classifier()
        )
        return {
            "status": "finished",
            "report": asdict(result.report),
            "retained_count": len(result.datasets),
            "limitation": "Bounded sample checks; results are not saved to PostgreSQL.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["api", "html", "browser", "collection"])
    parser.add_argument("url")
    parser.add_argument("--live", action="store_true", help="Explicitly allow network access")
    parser.add_argument("--offline-json")
    parser.add_argument("--include-ai", action="store_true")
    args = parser.parse_args()
    if not args.live and not args.offline_json:
        parser.error("Use --offline-json for replay, or --live for a new network observation.")
    if args.live and args.offline_json:
        parser.error("Choose either live observation or offline replay.")
    if args.offline_json and args.mode != "api":
        parser.error("Offline JSON is only supported for the API scenario.")
    if args.mode == "collection" and not args.include_ai:
        parser.error("Collection requires --include-ai to authorize model calls.")
    before, started = fingerprint(), time.monotonic()
    try:
        with collection_budget(seconds=DEFAULT_CONFIG.collection_max_duration_seconds):
            result = execute(
                args.mode, args.url, offline_json=args.offline_json, include_ai=args.include_ai
            )
    except CollectionStepError as exc:
        result = {
            "status": "failed",
            "code": exc.diagnostics[0].code,
            "failure_phase": exc.phase,
            "http_status": exc.http_status,
            "service_http_status": exc.service_http_status,
        }
    except PageFetchError as exc:
        result = {"status": "failed", "code": exc.diagnostics[0].code}
    except PipelineFailure as exc:
        result = {"status": "failed", "errors": [item.to_dict() for item in exc.diagnostics]}
    after = fingerprint()
    evidence = {
        "document_type": "search_lab_reproduction",
        "id": str(uuid4()),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "source_url": public_url(args.url),
        "offline": bool(args.offline_json),
        "collector_version": before if before == after else None,
        "version_changed_during_run": before != after,
        "duration_seconds": round(time.monotonic() - started, 3),
        "result": public_evidence(result),
    }
    folder = evidence_directory() / "reproductions"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = folder / (evidence["id"] + ".json")
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)
    print(
        json.dumps({"evidence_file": str(output), "result": evidence["result"]}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
