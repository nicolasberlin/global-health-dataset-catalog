"""Run the production app; control only external HTTP responses.

This script runs the application from the checkout in its own process.
Every response is raw HTTP response data: workers, parsers, votes, validation
and PostgreSQL writes retain their production implementations.
"""

from __future__ import annotations

import io
import json
import os
import socket
import sys
from email.message import Message
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

CASE = json.loads(Path(os.environ["E2E_SCENARIO_FILE"]).read_text())
RECORDS = CASE["records"]
RESPONSES = CASE["responses"]
MODEL_KEYS = {
    "fixture-deepseek": "fixture-deepseek-key",
    "fixture-gemma": "fixture-gemma-key",
    "fixture-apertus": "fixture-apertus-key",
}
JOURNAL = Path(os.environ["E2E_RUNTIME_DIR"]) / "external-calls.jsonl"
JOURNAL_LOCK = Lock()


def landing_body(record):
    metadata = {
        "@context": "https://schema.org",
        "@type": record["page_type"],
        "@id": record["url"],
        "url": record["url"],
        "name": record["title"],
        "description": record["description"],
        "publisher": {"@type": "Organization", "name": record["publisher"]},
        "datePublished": "2025-01-01",
        "spatialCoverage": record["country"],
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
    if record["page_type"] == "Dataset":
        metadata["distribution"] = {
            "@type": "DataDownload",
            "contentUrl": record["csv_url"],
            "encodingFormat": "text/csv",
        }
    return (
        f"<!doctype html><html><head><title>{record['title']}</title>"
        f'<meta name="description" content="{record["description"]}">'
        f'<meta name="publisher" content="{record["publisher"]}">'
        f'<link rel="canonical" href="{record["url"]}">'
        '<script type="application/ld+json">'
        + json.dumps(metadata)
        + f"</script></head><body><h1>{record['title']}</h1><p>{record['description']}</p>"
        f'<a href="{record["csv_url"]}">Download CSV data</a></body></html>'
    ).encode()


def record_key(url, field="url"):
    matches = [key for key, item in RECORDS.items() if item[field] == url]
    assert len(matches) == 1, f"Unregistered external URL: {url}"
    return matches[0]


def record(**event):
    # Voting runs in multiple threads. Each complete event must reach the driver.
    with JOURNAL_LOCK, JOURNAL.open("a") as stream:
        stream.write(json.dumps(event) + "\n")


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


class ExternalResponses:
    def __init__(self, *, models=False):
        self.models = models

    def open(self, request, *, timeout):
        try:
            assert timeout > 0, "Missing request timeout"
            assert not request.has_proxy(), "Unexpected proxy request"
            if self.models:
                kind, key, model, body = self.model_response(request)
                response = FixtureResponse(body, request.full_url, "application/json")
            else:
                kind, key, response = self.public_response(request)
                model = None
        except Exception as exception:
            # Workers may handle the exception; the driver still rejects this event.
            record(
                violation=True,
                url=request.full_url,
                method=request.get_method(),
                error=f"{type(exception).__name__}: {exception}",
            )
            raise
        record(
            kind=kind,
            candidate=key,
            model=model,
            url=request.full_url,
            method=request.get_method(),
            http_status=response.status,
        )
        if response.status >= 400:
            # An explicitly scripted HTTP error is an input, not a fixture violation.
            raise HTTPError(
                request.full_url, response.status, "Not Found", response.headers, response
            )
        return response

    @staticmethod
    def public_response(request):
        url, method = request.full_url, request.get_method()
        parsed = urlsplit(url)
        assert request.data is None, "Unexpected public request body"
        if (parsed.scheme, parsed.netloc, parsed.path) == ("https", "api.datacite.org", "/dois"):
            assert method == "GET", "DataCite must receive GET"
            assert not parsed.fragment, "Unexpected DataCite fragment"
            assert parse_qs(parsed.query, keep_blank_values=True) == {
                "query": ["malaria"],
                "resource-type-id": ["dataset"],
                "page[size]": ["10"],
                "sort": ["relevance"],
            }, "Unexpected DataCite search parameters"
            body = json.dumps(
                {
                    "data": [
                        {
                            "type": "dois",
                            "id": item["doi"],
                            "attributes": {
                                "doi": item["doi"],
                                "url": item["url"],
                                "titles": [{"title": item["title"]}],
                                "descriptions": [{"description": item["description"]}],
                                "publisher": item["publisher"],
                                "publicationYear": 2025,
                                "types": {"resourceTypeGeneral": "Dataset"},
                            },
                        }
                        for item in RECORDS.values()
                    ]
                }
            ).encode()
            return "discovery", None, FixtureResponse(body, url, "application/json")
        if any(item["url"] == url for item in RECORDS.values()):
            key = record_key(url)
            assert "eligible" in RESPONSES[key], "Rejected candidate fetched"
            assert method == "GET", "Landing page must receive GET"
            return (
                "landing",
                key,
                FixtureResponse(landing_body(RECORDS[key]), url, "text/html; charset=utf-8"),
            )
        key = record_key(url, "csv_url")
        spec, item = RESPONSES[key], RECORDS[key]
        assert spec.get("eligible") is True, "Ineligible dataset resource requested"
        assert method in {"HEAD", "GET"}, "Unexpected CSV request method"
        status = spec["csv_status"]
        if status == 404:
            assert method == "HEAD", "GET must not follow a definitive HEAD 404"
            return (
                "csv_head",
                key,
                FixtureResponse(b"Not found", url, "text/plain", method=method, status=404),
            )
        assert status == 200, "Unregistered CSV response"
        body = item["csv"].encode()
        if method == "GET":
            requested_range = request.get_header("Range", "")
            assert requested_range.startswith("bytes=0-"), "Expected bounded CSV sample"
            assert requested_range[8:].isdigit(), "Invalid sample range"
            assert int(requested_range[8:]) >= len(body) - 1, "Sample omits fixture rows"
        # The server returns the complete small file when ignoring Range.
        return "csv_" + method.lower(), key, FixtureResponse(body, url, "text/csv", method=method)

    @staticmethod
    def model_response(request):
        assert request.full_url == "https://inference-rcp.epfl.ch/v1/chat/completions", (
            "Unregistered model URL"
        )
        assert request.get_method() == "POST", "Models must receive POST"
        assert request.get_header("Content-type") == "application/json"
        body = json.loads(request.data)
        model = body["model"]
        assert model in MODEL_KEYS, "Unregistered model"
        assert request.get_header("Authorization") == "Bearer " + MODEL_KEYS[model], (
            "Unexpected synthetic model credentials"
        )
        assert body["response_format"] == {"type": "json_object"}
        messages = body["messages"]
        assert len(messages) == 2 and messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        evidence = json.loads(messages[1]["content"])
        if "repository_result" in evidence:
            assert evidence["search_query"] == "malaria", "Lost search query"
            candidate = evidence["repository_result"]
            key = record_key(candidate["url"])
            item = RECORDS[key]
            for field in ("title", "description", "publisher"):
                assert candidate[field] == item[field], f"Mixed candidate {field}"
            spec = RESPONSES[key]
            label = (
                spec["relevance_by_model"][model]
                if "relevance_by_model" in spec
                else spec["relevance"]
            )
            kind = "relevance"
            decision = {
                "label": label,
                "missing_information": [],
                "reason": "Malaria surveillance matches the query."
                if label == "relevant"
                else "The model judged the candidate unrelated to the search query.",
            }
        else:
            page = evidence["page"]
            key = record_key(page["url"])
            item = RECORDS[key]
            assert "eligible" in RESPONSES[key], "Unregistered page eligibility response"
            assert page["title"] == item["title"]
            assert page["publisher"] == item["publisher"]
            assert page["meta_description"] == item["description"]
            assert len(evidence["distributions"]) == 1
            distribution = evidence["distributions"][0]
            assert distribution["url"] == item["csv_url"] and distribution["format"] == "CSV"
            kind = "eligibility"
            accepted = RESPONSES[key]["eligible"]
            decision = {
                "accepted": accepted,
                "dataset_signals": {
                    "reason": "Individual public health dataset."
                    if accepted
                    else "Methodology article, not an individual dataset.",
                    "evidence": "Dataset metadata and a CSV distribution are present."
                    if accepted
                    else "The page explains methodology and links an illustrative CSV.",
                },
            }
        envelope = {"choices": [{"message": {"content": json.dumps(decision)}}]}
        return kind, key, model, json.dumps(envelope).encode()


def reject_uncontrolled_network(event, arguments):
    # Only database connections are allowed outside the controlled HTTP transports.
    if event == "socket.connect":
        address = arguments[1]
        if isinstance(address, tuple) and (address[0], address[1]) in DATABASE_ADDRESSES:
            return
    elif event == "socket.getaddrinfo":
        host, port = arguments[:2]
        if (host, str(port)) in ALLOWED_DNS:
            return
    else:
        return
    record(violation=True, error=f"Uncontrolled network operation: {event} {arguments[1:]!r}")
    raise AssertionError(f"Uncontrolled network operation: {event}")


if __name__ == "__main__":
    # Resolve only the isolated database before installing the Python network guard.
    database = urlsplit(os.environ["DATABASE_URL"])
    database_port = database.port or 5432
    api_port = int(os.environ["E2E_API_PORT"])
    DATABASE_ADDRESSES = {
        (entry[4][0], entry[4][1]) for entry in socket.getaddrinfo(database.hostname, database_port)
    }
    ALLOWED_DNS = {(database.hostname, str(database_port)), ("127.0.0.1", str(api_port))}
    sys.addaudithook(reject_uncontrolled_network)

    import uvicorn

    from collector.llm import client as llm_client
    from collector.network import fetch

    fetch.build_opener = lambda *handlers: ExternalResponses()
    llm_client.build_opener = lambda *handlers: ExternalResponses(models=True)

    # Use the real application factory and lifespan; only external responses are controlled.
    from app.main import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=api_port, lifespan="on", loop="asyncio")
