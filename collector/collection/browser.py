"""Trusted optional renderer client; cookies remain exclusively in the isolated service."""

from __future__ import annotations

import base64
import json
import os
import time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from collector.budget import (
    active_collection_budget,
    check_collection_budget,
    cleanup_request_budget,
    read_with_budget,
    remaining_timeout,
    request_budget,
)
from collector.collection.compatibility import to_strategy_result
from collector.collection.contracts import StrategyResult
from collector.collection.failures import CollectionResponseError, CollectionTransportError
from collector.collection.registry import default_registry
from collector.discovery.adapters.shared import DiscoveredPage
from collector.network.fetch import PageFetchError, decode_json_body, is_timeout_error
from collector.network.transport import (
    DeadlineHTTPHandler,
    DeadlineHTTPSHandler,
    RejectHTTPRedirects,
)
from collector.storage.models import HTTPProbe
from collector.validation.distributions import validate_distribution


class BrowserSession:
    def __init__(self, endpoint, token, config, *, registry=None):
        self.endpoint, self.token, self.config = endpoint.rstrip("/"), token, config
        self.session_id = None
        self.registry = default_registry(config) if registry is None else registry

    def request(self, action, payload, *, closing=False):
        budget = cleanup_request_budget(seconds=3) if closing else request_budget(seconds=31)
        with budget:
            return self._request(action, payload, closing=closing)

    def _request(self, action, payload, *, closing=False):
        service_status = None
        try:
            queue_deadline = time.monotonic() + (3 if closing else remaining_timeout(30))
            while True:
                timeout = 3 if closing else remaining_timeout(31)
                if action == "/render":
                    collection = active_collection_budget()
                    payload["budget_ms"] = int(
                        (min(300, collection.remaining()) if collection else 300) * 1000
                    )
                request = Request(
                    self.endpoint + action,
                    method="POST",
                    data=json.dumps(payload).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.token}",
                    },
                )
                try:
                    with build_opener(
                        ProxyHandler({}), DeadlineHTTPHandler(), DeadlineHTTPSHandler(),
                        RejectHTTPRedirects(),
                    ).open(request, timeout=timeout) as response:
                        service_status = response.status
                        data = read_with_budget(response, 2000001)
                    break
                except HTTPError as exc:
                    # A 429 explicitly means no session was created. Other POST failures
                    # are never replayed because their acknowledgement may have been lost.
                    if action != "/render" or exc.code != 429:
                        raise
                    if exc.fp is not None:
                        exc.fp.close()
                    if time.monotonic() >= queue_deadline:
                        raise CollectionTransportError(
                            "browser_unavailable", "fetch", service_http_status=429,
                        ) from exc
                    time.sleep(min(0.5, remaining_timeout(0.5)))
            if len(data) > 2000000:
                raise CollectionResponseError(
                    "browser_invalid_response", "decode", service_http_status=service_status,
                )
            decoded = decode_json_body(data)
            if not isinstance(decoded, dict):
                raise ValueError("Invalid renderer response")
            return decoded
        except HTTPError as exc:
            code, phase = "browser_unavailable", "fetch"
            try:
                body = decode_json_body(read_with_budget(exc, 4096)) if exc.fp else None
                allowed = {
                    "browser_timeout", "browser_render_failed", "browser_navigation_failed",
                    "browser_worker_exited", "browser_invalid_response",
                }
                if isinstance(body, dict) and body.get("error") in allowed:
                    code, phase = body["error"], "render"
            except (ValueError, OSError):
                check_collection_budget()
            finally:
                if exc.fp is not None:
                    exc.fp.close()
            raise CollectionTransportError(
                code, phase, service_http_status=exc.code,
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            check_collection_budget()
            code = "browser_timeout" if is_timeout_error(exc) else "browser_unavailable"
            raise CollectionTransportError(code, "fetch") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise CollectionResponseError(
                "browser_invalid_response", "decode", service_http_status=service_status,
            ) from exc

    def render(self, url, *, metadata_url=None):
        data = self.request(
            "/render",
            {
                "url": url,
                "metadata_url": metadata_url,
                "budget_ms": int(remaining_timeout(300) * 1000),
            },
        )
        if not isinstance(data.get("session_id"), str) or not data["session_id"]:
            raise CollectionResponseError("browser_invalid_response", "render")
        self.session_id = data["session_id"]
        metadata_code = data.get("metadata_code", "")
        if metadata_code not in {
            "repository_http_error", "repository_network_error", "repository_invalid_json",
            "repository_response_too_large",
        }:
            metadata_code = ""
        metadata_status = data.get("metadata_http_status")
        if type(metadata_status) is not int or not 100 <= metadata_status <= 599:
            metadata_status = None
        if data.get("metadata") is not None:
            selection = self.registry.select(url)
            if selection and selection.api_url == metadata_url:
                try:
                    result = to_strategy_result(
                        selection.connector.normalize(url, data["metadata"]), "browser",
                    )
                except ValueError:
                    metadata_code = "repository_metadata_invalid"
                else:
                    result.http_status = data.get("http_status")
                    result.metadata_http_status = metadata_status
                    return result
        if not isinstance(data.get("html"), str) or not isinstance(data.get("final_url"), str):
            raise CollectionResponseError(
                "browser_invalid_response", "render", http_status=data.get("http_status"),
            )
        return StrategyResult(
            page=DiscoveredPage(url=data["final_url"], discovery_method="browser"),
            html=data["html"],
            final_url=data["final_url"],
            http_status=data.get("http_status"),
            metadata_code=metadata_code,
            metadata_http_status=metadata_status,
        )

    def probe(self, url, method, timeout, max_bytes, headers=None):
        try:
            data = self.request(
                "/probe",
                {
                    "session_id": self.session_id,
                    "url": url,
                    "method": method,
                    "max_bytes": max_bytes,
                    "timeout_ms": int(remaining_timeout(timeout) * 1000),
                },
            )
            return HTTPProbe(
                url=url,
                final_url=data["final_url"],
                status_code=data["status_code"],
                headers=data["headers"],
                body_sample=base64.b64decode(data["body_base64"], validate=True),
                sample_truncated=data["sample_truncated"],
            )
        except (PageFetchError, ValueError, KeyError):
            return HTTPProbe(
                url=url,
                final_url=url,
                status_code=None,
                error="Browser resource check was inconclusive.",
            )

    def validate(self, distribution):
        return validate_distribution(
            distribution,
            timeout=self.config.request_timeout_seconds,
            max_sample_bytes=self.config.max_sample_bytes,
            probe=self.probe,
        )

    def close(self):
        if self.session_id:
            try:
                self.request("/close", {"session_id": self.session_id}, closing=True)
            except PageFetchError:
                pass  # Service lease expires and kills the process even after client disconnect.
            self.session_id = None


@contextmanager
def configured_browser(config, source_url=None):
    endpoint = os.getenv("COLLECTION_BROWSER_URL", "")
    token = os.getenv("COLLECTION_BROWSER_TOKEN", "")
    hosts = {
        x.strip() for x in os.getenv("COLLECTION_BROWSER_HOSTS", "dataverse.harvard.edu").split(",")
    }
    if not endpoint or (source_url and urlsplit(source_url).hostname not in hosts):
        yield None
        return
    parsed = urlsplit(endpoint)
    # This endpoint is trusted deployment config, never derived from a candidate URL.
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(token) < 32
    ):
        raise RuntimeError("Invalid collection browser configuration")
    session = BrowserSession(endpoint, token, config)
    try:
        yield session
    finally:
        session.close()
