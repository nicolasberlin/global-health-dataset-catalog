"""Candidate-scoped API/HTML/browser resolution with shared validation and deadline."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from functools import partial
from urllib.error import HTTPError, URLError

from collector.budget import CollectionBudgetExceeded, check_collection_budget, collection_budget
from collector.collection.compatibility import to_strategy_result
from collector.collection.contracts import MethodAttempt, StrategyResult, public_url
from collector.collection.failures import CollectionMetadataError, CollectionStepError
from collector.collection.http import JsonResponse, fetch_record_json
from collector.collection.pipeline import classify_resolution, eligible_resources
from collector.collection.registry import ConnectorRegistry, default_registry
from collector.config import CollectorConfig
from collector.diagnostics import Diagnostic, PipelineFailure
from collector.discovery.adapters.shared import DiscoveredPage
from collector.fetch import PageFetchError, fetch_public_html
from collector.storage.models import CollectionReport, CollectionResult
from collector.validation.downloads import page_access_diagnostic, validate_distribution


def now():
    return datetime.now(timezone.utc).isoformat()


def collect_record(
    url: str,
    config: CollectorConfig,
    *,
    fetch_html=None,
    fetch_json=None,
    validate=None,
    classifier=None,
    browser=None,
    observe=None,
    registry: ConnectorRegistry | None = None,
) -> CollectionResult:
    custom_html = fetch_html is not None
    fetch_html = fetch_html or partial(
        fetch_public_html, timeout=config.request_timeout_seconds, user_agent=config.user_agent
    )
    fetch_json = fetch_json or (
        None
        if custom_html
        else partial(
            fetch_record_json, timeout=config.request_timeout_seconds, user_agent=config.user_agent,
        )
    )
    validate = validate or partial(
        validate_distribution,
        timeout=config.request_timeout_seconds,
        max_sample_bytes=config.max_sample_bytes,
        user_agent=config.user_agent,
    )
    attempts, failed_checks, unresolved = [], [], []
    datasets = []
    seen = set()
    checks_count = 0
    rejected = False
    analyzed = False
    known_record = None
    coverage = {
        "policy": "bounded_validated_resources",
        "max_saved": config.max_distributions_saved,
        "max_checks": config.max_distribution_attempts,
        "discovered": 0,
        "checked": 0,
        "validated": 0,
        "discovery": "unknown",
        "limited": False,
    }
    selection = (default_registry(config) if registry is None else registry).select(url)
    reference_identity = selection.connector.reference_identity(url).to_dict() if selection else {}
    api_url = selection.api_url if selection else None
    api_method = selection.connector.method if selection else None
    methods = ([api_method] if api_url and fetch_json else []) + ["html"]
    if browser is not None:
        methods.append("browser")
    with collection_budget(seconds=config.collection_max_duration_seconds):
        for method in methods:
            if checks_count >= config.max_distribution_attempts:
                coverage["limited"] = True
                break
            attempt = MethodAttempt(method=method, started_at=now(), requested_url=public_url(url))
            attempts.append(attempt)
            index = len(attempts) - 1
            if observe:
                observe(index, asdict(attempt))
            phase = "fetch"
            try:
                check_collection_budget()
                if method == api_method:
                    attempt.requested_url = public_url(api_url)
                    response = fetch_json(api_url)
                    if isinstance(response, JsonResponse):
                        attempt.http_status = response.http_status
                        attempt.final_url = public_url(response.final_url)
                        payload = response.payload
                    else:
                        payload = response  # Legacy injected fetchers supply no HTTP evidence.
                    phase = "normalize"
                    try:
                        record = selection.connector.normalize(url, payload)
                    except ValueError as exc:
                        raise CollectionMetadataError("repository_metadata_invalid", phase) from exc
                    resolved = to_strategy_result(record, method)
                elif method == "html":
                    fetched = fetch_html(url)
                    attempt.http_status = fetched.status_code
                    attempt.final_url = public_url(fetched.final_url)
                    if fetched.content_type and "html" not in fetched.content_type.lower():
                        raise PageFetchError(
                            "Non-HTML landing response", code="verification_unconfirmed"
                        )
                    resolved = StrategyResult(
                        page=DiscoveredPage(url=fetched.final_url, discovery_method="html"),
                        html=fetched.html,
                        final_url=fetched.final_url,
                        http_status=fetched.status_code,
                    )
                else:
                    phase = "render"
                    resolved = browser.render(url, metadata_url=api_url)
                    attempt.http_status = resolved.http_status
                attempt.final_url = attempt.final_url or public_url(
                    resolved.final_url or resolved.page.url
                )
                attempt.metadata_code = resolved.metadata_code
                attempt.metadata_http_status = resolved.metadata_http_status
                phase = "normalize"
                if resolved.record is not None:
                    known_record = resolved.record
                resources = eligible_resources(resolved)
                if selection is not None:
                    resources = selection.connector.scope_resources(url, resources, known_record)
                analyzed = True
                attempt.resource_count = len(resources)
                attempt.discovery_coverage = resolved.discovery_coverage
                coverage["discovery"] = resolved.discovery_coverage
                coverage["discovered"] = max(int(coverage["discovered"]), len(resources))
                if not resources:
                    barrier = page_access_diagnostic(resolved.html) if resolved.html else None
                    if barrier:
                        raise PageFetchError("Landing access barrier", code=barrier.code)
                    attempt.status, attempt.code = "empty", "no_download_links"
                    if method == api_method and resolved.discovery_coverage == "listed":
                        unresolved.clear()
                        break  # Authoritative listing is empty in the supported record scope.
                    continue
                phase = "classify"
                dataset = classify_resolution(
                    resolved, resources, config, classifier,
                    record_url=url if selection else None,
                    known_record=known_record,
                    record_identity=(to_strategy_result(known_record, method).page.record_identity
                                     if known_record else reference_identity),
                )
                if dataset is not None and known_record is not None:
                    dataset = replace(
                        dataset, record_identity=to_strategy_result(
                            known_record, method,
                        ).page.record_identity,
                    )
                if dataset is None:
                    attempt.status, attempt.code = "rejected", "page_rejected"
                    rejected = True
                    unresolved.clear()
                    break  # A valid semantic rejection is not retried for a more favorable vote.
                retained, validations = [], []
                phase = "validate"
                for resource in sorted(resources, key=lambda x: x.probability, reverse=True):
                    if checks_count >= config.max_distribution_attempts:
                        coverage["limited"] = True
                        break
                    key = str(resource.signals.get("resource_key") or resource.url)
                    # The same resource may need a session-bound probe after a failed HTTP probe.
                    probe_key = (key, "browser" if method == "browser" else "http")
                    if probe_key in seen:
                        continue
                    seen.add(probe_key)
                    check_collection_budget()
                    checks_count += 1
                    validator = browser.validate if method == "browser" else validate
                    validation = validator(resource)
                    attempt.checks.append(
                        {
                            "resource_key": public_url(key) if "://" in key else key,
                            "url": public_url(resource.url),
                            "format": validation.format,
                            "status": validation.status,
                            "http_status": validation.http_status,
                            "code": "" if validation.ok else "verification_unconfirmed",
                        }
                    )
                    coverage["checked"] = checks_count
                    if validation.ok:
                        retained.append(
                            replace(
                                resource, format=validation.format, mime_type=validation.mime_type
                            )
                        )
                        validations.append(validation)
                        coverage["validated"] = len(retained)
                        if len(retained) >= config.max_distributions_saved:
                            coverage["limited"] = len(resources) > len(retained)
                            break
                    else:
                        failed_checks.append(validation)
                if retained:
                    datasets.append(
                        replace(
                            dataset,
                            distributions=retained,
                            validation_results=validations,
                            discovery_method=method,
                        )
                    )
                    attempt.status = "succeeded"
                    unresolved.clear()
                    break
                attempt.status, attempt.code = "inconclusive", "resource_checks_failed"
                unresolved.append(Diagnostic("verification_unconfirmed", "validation"))
            except CollectionBudgetExceeded as exc:
                attempt.status, attempt.code = "failed", "collection_budget_exhausted"
                attempt.failure_phase = phase
                unresolved.extend(exc.diagnostics)
                break
            except CollectionStepError as exc:
                attempt.status, attempt.code = "failed", exc.diagnostics[0].code
                attempt.failure_phase = exc.phase
                if exc.http_status is not None:
                    attempt.http_status = exc.http_status
                if exc.final_url:
                    attempt.final_url = public_url(exc.final_url)
                attempt.service_http_status = exc.service_http_status
                unresolved.extend(exc.diagnostics)
            except PageFetchError as exc:
                code = exc.diagnostics[0].code
                cause = exc.__cause__
                if isinstance(cause, HTTPError):
                    attempt.http_status = cause.code
                    code = "repository_http_error"
                elif isinstance(cause, (URLError, OSError)):
                    code = "repository_timeout" if (
                        isinstance(cause, TimeoutError)
                        or isinstance(getattr(cause, "reason", None), TimeoutError)
                    ) else "repository_network_error"
                blocked = code in {"verification_unconfirmed", "access_restricted"}
                attempt.status, attempt.code = "blocked" if blocked else "failed", code
                attempt.failure_phase = "access" if blocked else phase
                unresolved.append(Diagnostic(code, "collection"))
            except (ValueError, OSError) as exc:
                cause = exc.__cause__
                if isinstance(cause, HTTPError):
                    attempt.http_status = cause.code
                code = "repository_http_error" if isinstance(cause, HTTPError) else (
                    "repository_network_error" if isinstance(exc, OSError) else "processing_failed"
                )
                attempt.status, attempt.code = "failed", code
                attempt.failure_phase = phase
                unresolved.append(Diagnostic(code, "collection"))
            except PipelineFailure as exc:
                attempt.status, attempt.code = "failed", exc.diagnostics[0].code
                attempt.failure_phase = phase
                raise  # Preserve existing classifier/persistence retry policy.
            finally:
                attempt.finished_at = now()
                if attempt.status == "running":
                    attempt.status, attempt.code = "failed", "processing_failed"
                if attempt.code:
                    attempt.reason = Diagnostic(attempt.code, "collection").message
                if observe:
                    observe(index, asdict(attempt))
        unique_errors = list({(e.code, e.stage, e.recovery): e for e in unresolved}.values())
        return CollectionResult(
            datasets=datasets,
            report=CollectionReport(
                discovered_count=1,
                analyzed_count=int(analyzed),
                accepted_count=len(datasets),
                rejected_count=int(rejected or (not datasets and not unique_errors)),
                invalid_distribution_count=len(failed_checks),
                validation_failures=failed_checks,
                errors=unique_errors,
                verification_complete=not unique_errors,
                discovery_methods=tuple(a.method for a in attempts),
                method_attempts=[asdict(a) for a in attempts],
                coverage=coverage,
            ),
        )
