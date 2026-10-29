from __future__ import annotations

import io
import json
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest
from app.db.collection.traces import safe_observation

from collector.classification.page import PageClassification
from collector.collection.browser import BrowserSession
from collector.collection.connectors.dataverse import DataverseConnector
from collector.collection.failures import CollectionTransportError
from collector.collection.http import JsonResponse
from collector.config import DEFAULT_CONFIG
from collector.diagnostics import Diagnostic
from collector.fetch import FetchedPage
from collector.main import collect_repository_candidate_with_report
from collector.storage.models import ValidationResult

PID = "doi:10.7910/DVN/AXRYQD/RTPFQI"
URL = "https://dataverse.harvard.edu/file.xhtml?persistentId=" + PID
API = "https://dataverse.harvard.edu/api/v1/files/:persistentId?persistentId="


class Accept:
    def classify(self, page, resources):
        return PageClassification(True)


def test_retry_after_prevents_fallback_requests_to_same_repository():
    def limited(_):
        error = CollectionTransportError("repository_http_error", "fetch", http_status=429)
        error.diagnostics = [Diagnostic(
            "repository_http_error", "collection",
            retry_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
        )]
        raise error

    result = collect_repository_candidate_with_report(
        "https://zenodo.org/records/123", fetch_json=limited,
        fetch_html=lambda _: pytest.fail("Fallback must respect provider deadline"),
        classifier=Accept(),
    )
    assert len(result.report.method_attempts) == 1
    assert result.report.method_attempts[0]["http_status"] == 429
    assert result.report.errors[0].retry_at is not None


def test_html_socket_timeout_is_classified_as_timeout():
    def slow(_):
        from collector.fetch import PageFetchError

        raise PageFetchError("transport failed") from socket.timeout()

    result = collect_repository_candidate_with_report(
        "https://example.org/dataset", fetch_html=slow, classifier=Accept(),
    )
    assert result.report.method_attempts[0]["code"] == "repository_timeout"


def test_default_metadata_transport_uses_configured_policy(monkeypatch):
    import collector.collection.orchestrator as orchestrator

    calls = []

    def fetch(url, **kwargs):
        calls.append(kwargs)
        raise CollectionTransportError("repository_http_error", "fetch", http_status=404)

    monkeypatch.setattr(orchestrator, "fetch_record_json", fetch)
    monkeypatch.setattr(
        orchestrator, "fetch_public_html",
        lambda url, **kwargs: FetchedPage(url, url, "<html>No files</html>", 200, "text/html"),
    )
    config = replace(
        DEFAULT_CONFIG, record_request_timeout_seconds=25,
        record_max_attempts=2, record_retry_max_wait_seconds=15,
    )
    collect_repository_candidate_with_report(
        "https://zenodo.org/records/123", config=config, classifier=Accept(),
    )
    assert calls == [{
        "timeout": 25, "max_attempts": 2, "max_retry_wait": 15,
        "user_agent": config.user_agent,
    }]


@pytest.mark.parametrize("value,expected", [(2, 2), (True, None), (61, None), ("2", None)])
def test_metadata_request_count_is_sanitized(value, expected):
    clean = safe_observation({"request_attempts": value})
    assert clean.get("request_attempts") == expected


def test_dataverse_file_endpoints_preserve_record_and_version_scope():
    connector = DataverseConnector(DEFAULT_CONFIG.dataverse_hosts)
    assert connector.api_url(URL).startswith(API)
    assert "/metadata" not in connector.api_url(URL)
    assert connector.api_url(URL + "&version=2.0").startswith(
        "https://dataverse.harvard.edu/api/v1/files/:persistentId/versions/2.0?"
    )
    assert connector.api_url("https://dataverse.harvard.edu/file.xhtml?fileId=178154") == (
        "https://dataverse.harvard.edu/api/v1/files/178154"
    )


def test_real_metadata_shape_fails_normalization_not_transport():
    payload = {"label": "survey.tab", "id": 2331381, "restricted": False}
    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=lambda api: JsonResponse(api, api, 200, "text/plain", payload),
        fetch_html=lambda url: FetchedPage(url, url, "<html>No links</html>", 200, "text/html"),
    )
    attempt = result.report.method_attempts[0]
    assert attempt["http_status"] == 200
    assert attempt["code"] == "repository_metadata_invalid"
    assert attempt["failure_phase"] == "normalize"
    assert attempt["final_url"].startswith(API)
    assert not result.datasets and not result.report.verification_complete


def test_complete_file_representation_uses_datafile_id_not_metadata_id():
    payload = {
        "status": "OK",
        "data": {
            "id": 2331381,
            "label": "survey.tab",
            "dataFile": {
                "id": 178154,
                "filename": "survey.tab",
                "persistentId": PID,
                "contentType": "text/tab-separated-values",
            },
        },
    }

    def fetch(api):
        assert "/metadata" not in api
        return JsonResponse(api, api, 200, "application/json", payload)

    def validate(resource):
        assert resource.url.endswith("/api/access/datafile/178154")
        return ValidationResult(resource.url, resource.url, "TSV", True, 206)

    result = collect_repository_candidate_with_report(
        URL,
        fetch_json=fetch,
        classifier=Accept(),
        validate=validate,
        fetch_html=lambda _: pytest.fail("Successful API must stop fallback"),
    )
    assert len(result.datasets) == 1 and not result.report.errors
    assert result.datasets[0].record_identity["kind"] == "file"
    assert result.report.method_attempts[0]["http_status"] == 200


@pytest.mark.parametrize(
    "service_code,expected",
    [
        ("browser_navigation_failed", "browser_navigation_failed"),
        ("browser_worker_exited", "browser_worker_exited"),
        ("browser_timeout", "browser_timeout"),
        ("secret-provider-error", "browser_unavailable"),
    ],
)
def test_browser_service_failure_does_not_become_repository_failure(
    monkeypatch, service_code, expected
):
    class FailedService:
        def open(self, *args, **kwargs):
            raise HTTPError(
                "http://renderer/render",
                503,
                "secret",
                {},
                io.BytesIO(json.dumps({"error": service_code}).encode()),
            )

    monkeypatch.setattr(
        "collector.collection.browser.build_opener", lambda *a, **k: FailedService()
    )
    session = BrowserSession("http://renderer", "secret-token", DEFAULT_CONFIG)
    with pytest.raises(CollectionTransportError) as caught:
        session.render(URL)
    assert caught.value.diagnostics[0].code == expected
    assert caught.value.http_status is None  # This is service HTTP, not Harvard HTTP.
    assert caught.value.service_http_status == 503
    assert "secret" not in str(caught.value)


def test_browser_optional_metadata_error_preserves_html_and_warning(monkeypatch):
    session = BrowserSession("http://renderer", "secret-token", DEFAULT_CONFIG)
    monkeypatch.setattr(
        session,
        "request",
        lambda *a, **k: {
            "session_id": "session",
            "metadata": {"id": 2331381, "label": "survey.tab"},
            "metadata_http_status": 200,
            "http_status": 200,
            "html": '<a href="/api/access/datafile/:persistentId?persistentId='
            + PID
            + '">survey.tab</a>',
            "final_url": URL,
        },
    )
    resolved = session.render(
        URL, metadata_url=DataverseConnector(DEFAULT_CONFIG.dataverse_hosts).api_url(URL)
    )
    assert resolved.html and resolved.metadata_code == "repository_metadata_invalid"
    assert resolved.metadata_http_status == 200


def test_trace_rebuilds_reason_and_rejects_uncontrolled_phase():
    clean = safe_observation(
        {
            "method": "browser",
            "code": "browser_navigation_failed",
            "failure_phase": "render",
            "reason": "SECRET COOKIE",
            "service_http_status": 503,
            "metadata_code": "repository_metadata_invalid",
            "metadata_http_status": 200,
        }
    )
    assert clean["failure_phase"] == "render" and clean["service_http_status"] == 503
    assert "SECRET" not in str(clean)
    assert "failure_phase" not in safe_observation({"failure_phase": "SECRET"})
