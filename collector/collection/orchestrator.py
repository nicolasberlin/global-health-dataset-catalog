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
from collector.collection.resources import ResourceCheckState, retain_validated_resources
from collector.config import CollectorConfig
from collector.diagnostics import Diagnostic, PipelineFailure
from collector.discovery.adapters.shared import DiscoveredPage
from collector.extraction.errors import ExtractionError
from collector.network.fetch import PageFetchError, fetch_public_html, is_timeout_error
from collector.storage.models import CollectionReport, CollectionResult
from collector.validation.distributions import page_access_diagnostic, validate_distribution


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
            fetch_record_json, timeout=config.record_request_timeout_seconds,
            max_attempts=config.record_max_attempts,
            max_retry_wait=config.record_retry_max_wait_seconds, user_agent=config.user_agent,
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
    check_state = ResourceCheckState(failures=failed_checks)
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
            if check_state.checked >= config.max_distribution_attempts:
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
                    fetch_metadata = getattr(selection.connector, "fetch_metadata", None)
                    if fetch_metadata:
                        evidence, request_count = {}, [0]

                        def related_json(
                            metadata_url, *, evidence=evidence, request_count=request_count,
                        ):
                            try:
                                result = fetch_json(metadata_url)
                            except CollectionStepError as exc:
                                request_count[0] += getattr(exc, "request_attempts", None) or 1
                                exc.request_attempts = request_count[0]
                                raise
                            if isinstance(result, JsonResponse):
                                evidence.update(
                                    http_status=result.http_status, final_url=result.final_url,
                                )
                                request_count[0] += result.request_attempts
                            else:
                                request_count[0] += 1
                            return result

                        try:
                            response = fetch_metadata(url, related_json)
                        except CollectionStepError as exc:
                            exc.request_attempts = request_count[0] or None
                            raise
                        except ValueError as exc:
                            if isinstance(exc.__cause__, HTTPError):
                                raise  # Preserve legacy injected transport failures.
                            error = CollectionMetadataError(
                                "repository_metadata_invalid", "normalize", **evidence,
                            )
                            error.request_attempts = request_count[0] or None
                            raise error from exc
                    else:
                        response = fetch_json(api_url)
                    if isinstance(response, JsonResponse):
                        attempt.request_attempts = response.request_attempts
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
                resources = eligible_resources(resolved, expected_identity=reference_identity)
                if selection is not None:
                    resources = selection.connector.scope_resources(url, resources, known_record)
                analyzed = True
                attempt.resource_count = len(resources)
                attempt.discovery_coverage = resolved.discovery_coverage
                coverage["discovery"] = resolved.discovery_coverage
                coverage["discovered"] = max(int(coverage["discovered"]), len(resources))
                if not resources:
                    if (resolved.snapshot is not None
                            and resolved.snapshot.dataset_metadata_ambiguous):
                        raise ExtractionError(
                            "Dataset identity remains ambiguous.",
                            code="dataset_identity_ambiguous",
                        )
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
                phase = "validate"

                def record_check(resource, validation, *, attempt=attempt):
                    key = str(resource.signals.get("resource_key") or resource.url)
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
                    coverage["checked"] = check_state.checked

                selected = retain_validated_resources(
                    resources, config, browser.validate if method == "browser" else validate,
                    state=check_state, context="browser" if method == "browser" else "http",
                    on_check=record_check,
                )
                retained, validations = selected.resources, selected.validations
                coverage["validated"] = len(retained)
                coverage["limited"] = coverage["limited"] or selected.limited
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
                    if selected.budget_exhausted:
                        attempt.code = "collection_budget_exhausted"
                        unresolved.append(Diagnostic("collection_budget_exhausted", "collection"))
                    break
                attempt.status, attempt.code = "inconclusive", "resource_checks_failed"
                unresolved.append(Diagnostic("verification_unconfirmed", "validation"))
            except CollectionBudgetExceeded as exc:
                attempt.status, attempt.code = "failed", "collection_budget_exhausted"
                attempt.failure_phase = phase
                unresolved.extend(exc.diagnostics)
                break
            except ExtractionError as exc:
                attempt.status, attempt.code = "failed", exc.code
                attempt.failure_phase = "normalize"
                unresolved.append(Diagnostic(exc.code, "collection"))
            except CollectionStepError as exc:
                attempt.request_attempts = getattr(exc, "request_attempts", None)
                attempt.status, attempt.code = "failed", exc.diagnostics[0].code
                attempt.failure_phase = exc.phase
                if exc.http_status is not None:
                    attempt.http_status = exc.http_status
                if exc.final_url:
                    attempt.final_url = public_url(exc.final_url)
                attempt.service_http_status = exc.service_http_status
                unresolved.extend(exc.diagnostics)
                # A pending provider deadline also applies to HTML/browser requests
                # to this repository; a fallback must not bypass Retry-After.
                if any(
                    item.retry_at and datetime.fromisoformat(item.retry_at)
                    > datetime.now(timezone.utc) for item in exc.diagnostics
                ):
                    break
            except PageFetchError as exc:
                code = exc.diagnostics[0].code
                cause = exc.__cause__
                if isinstance(cause, HTTPError):
                    attempt.http_status = cause.code
                    code = "repository_http_error"
                elif isinstance(cause, (URLError, OSError)):
                    code = "repository_timeout" if is_timeout_error(cause) else (
                        "repository_network_error"
                    )
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
