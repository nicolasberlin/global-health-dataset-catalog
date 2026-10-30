"""Uvicorn test entry point: real application, deterministic external transports.

Never deploy this module. Tests provide a disposable PostgreSQL schema and
synthetic credentials; no provider or model request leaves the process.
"""

from __future__ import annotations

import io
import json
import os
import time
from email.message import Message
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app import lifecycle, main

from collector.budget import check_collection_budget
from collector.classification import llm_client
from collector.execution import check_execution_active
from collector.network import fetch

LANDING_URL = "https://fixtures.example/records/malaria"
CSV_URL = "https://fixtures.example/files/malaria.csv"
CSV_BODY = b"country,year,cases\nKenya,2024,12\nKenya,2025,9\n"
HTML_BODY = (
    '<!doctype html><html><head><title>Malaria surveillance dataset</title>'
    '<script type="application/ld+json">'
    + json.dumps({
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": LANDING_URL,
        "url": LANDING_URL,
        "name": "Malaria surveillance dataset",
        "description": "Malaria surveillance case counts in Kenya, 2024 and 2025.",
        "publisher": {"@type": "Organization", "name": "Fixture Public Health Institute"},
        "datePublished": "2025-01-01",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "spatialCoverage": "Kenya",
        "distribution": {
            "@type": "DataDownload", "contentUrl": CSV_URL, "encodingFormat": "text/csv",
        },
    })
    + '</script></head><body><h1>Malaria surveillance dataset</h1>'
    '<p>Download public health malaria surveillance case counts for Kenya.</p>'
    f'<a href="{CSV_URL}">Download malaria CSV data</a></body></html>'
).encode()


class FixtureResponse(io.BytesIO):
    def __init__(self, body, url, content_type, *, method="GET", status=200):
        super().__init__(body if method != "HEAD" else b"")
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))
        self._url = url

    def geturl(self):
        return self._url


class PublicFixtureTransport:
    def open(self, request, *, timeout):
        assert timeout > 0
        parsed = urlsplit(request.full_url)
        if parsed.hostname == "api.datacite.org" and parsed.path == "/dois":
            assert parse_qs(parsed.query)["query"] == ["malaria"]
            body = json.dumps({"data": [{
                "type": "dois",
                "id": "10.1234/malaria-fixture",
                "attributes": {
                    "doi": "10.1234/malaria-fixture",
                    "url": LANDING_URL,
                    "titles": [{"title": "Malaria surveillance dataset"}],
                    "descriptions": [{"description": "Malaria case counts in Kenya."}],
                    "publisher": "Fixture Public Health Institute",
                    "publicationYear": 2025,
                    "types": {"resourceTypeGeneral": "Dataset"},
                },
            }]}).encode()
            return FixtureResponse(body, request.full_url, "application/json")
        if request.full_url == LANDING_URL:
            gate = os.environ.get("API_FIXTURE_COLLECTION_GATE")
            if gate and Path(gate).exists():
                Path(gate + ".started").touch()
                while Path(gate).exists():
                    check_execution_active()
                    check_collection_budget()
                    time.sleep(0.01)
            return FixtureResponse(HTML_BODY, LANDING_URL, "text/html; charset=utf-8")
        if request.full_url == CSV_URL:
            return FixtureResponse(
                CSV_BODY, CSV_URL, "text/csv", method=request.get_method(),
            )
        raise AssertionError(f"Unregistered external request: {request.full_url}")


class ModelFixtureTransport:
    def open(self, request, *, timeout):
        assert timeout > 0
        payload = json.loads(request.data)
        evidence = json.loads(payload["messages"][1]["content"])
        if "repository_result" in evidence:
            decision = {
                "label": "relevant", "reason": "Malaria surveillance matches the query.",
                "missing_information": [],
            }
        else:
            assert "page" in evidence
            decision = {
                "accepted": True,
                "dataset_signals": {
                    "reason": "Individual public health dataset.",
                    "evidence": "Dataset metadata and a CSV distribution are present.",
                },
            }
        body = json.dumps({"choices": [{"message": {"content": json.dumps(decision)}}]})
        return FixtureResponse(body.encode(), request.full_url, "application/json")


# Keep production admission, workers, voting, parsing, validation and persistence.
fetch.build_opener = lambda *handlers: PublicFixtureTransport()
llm_client.build_opener = lambda *handlers: ModelFixtureTransport()
lifecycle.persisted_workers = partial(lifecycle.persisted_workers, poll_interval=0.02)
app = main.app
