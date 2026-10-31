# Python Function Index

Snapshot of the working-tree code on **31 October 2026**, based on Git commit `af14644`, including the independent core API and public Search Lab. The private web interface is excluded.

This index lists **864 function and method definitions in 144 project Python source files**, excluding tests. It includes private functions, methods, properties and named local functions. Lambdas and methods generated automatically by dataclasses are not named source definitions and are excluded.

For an overview of the application, read the [technical design document](../technical-design-document.md). For the public HTTP contract, see the [API integration guide](../api-integration.md). This index helps locate exact signatures; it does not attempt to reconstruct dynamic calls.

Names and signatures are extracted from Python syntax without importing or executing the project. Annotations and default values come from the source code. `async` identifies a coroutine; `contextmanager` and `asynccontextmanager` identify `with` or `async with` contexts. `<local>` identifies a function defined inside another function.

Each function is indexed in its defining module. Application callers import the owning `app.db` module directly; the former database re-export facade has been removed. JavaScript in the browser service and Search Lab is excluded from the Python counts.

Source links point to line numbers in this snapshot. Positions may change when the code is edited.

## Coverage

| Directory | Files with functions | Definitions |
| --- | ---: | ---: |
| `backend/` | 66 | 294 |
| `browser/` | 2 | 7 |
| `collector/` | 65 | 470 |
| `scripts/` | 3 | 52 |
| `search_lab/` | 8 | 41 |

## Files

- [backend/app/api/middleware.py](#backend-app-api-middleware-py) — 8 definitions
- [backend/app/api/presenters/catalog.py](#backend-app-api-presenters-catalog-py) — 3 definitions
- [backend/app/api/presenters/classification.py](#backend-app-api-presenters-classification-py) — 3 definitions
- [backend/app/api/presenters/collection.py](#backend-app-api-presenters-collection-py) — 2 definitions
- [backend/app/api/presenters/search.py](#backend-app-api-presenters-search-py) — 3 definitions
- [backend/app/api/routes/catalog.py](#backend-app-api-routes-catalog-py) — 1 definition
- [backend/app/api/routes/diagnostics.py](#backend-app-api-routes-diagnostics-py) — 1 definition
- [backend/app/api/routes/searches.py](#backend-app-api-routes-searches-py) — 5 definitions
- [backend/app/api/routes/sessions.py](#backend-app-api-routes-sessions-py) — 1 definition
- [backend/app/api/schemas/classification.py](#backend-app-api-schemas-classification-py) — 2 definitions
- [backend/app/api/schemas/search.py](#backend-app-api-schemas-search-py) — 1 definition
- [backend/app/api/search_progress.py](#backend-app-api-search_progress-py) — 1 definition
- [backend/app/auth/security.py](#backend-app-auth-security-py) — 14 definitions
- [backend/app/auth/sessions.py](#backend-app-auth-sessions-py) — 6 definitions
- [backend/app/db/catalog/datasets.py](#backend-app-db-catalog-datasets-py) — 6 definitions
- [backend/app/db/catalog/distributions.py](#backend-app-db-catalog-distributions-py) — 5 definitions
- [backend/app/db/catalog/observations.py](#backend-app-db-catalog-observations-py) — 4 definitions
- [backend/app/db/catalog/search.py](#backend-app-db-catalog-search-py) — 2 definitions
- [backend/app/db/classification/candidates.py](#backend-app-db-classification-candidates-py) — 5 definitions
- [backend/app/db/classification/completion.py](#backend-app-db-classification-completion-py) — 1 definition
- [backend/app/db/classification/jobs.py](#backend-app-db-classification-jobs-py) — 4 definitions
- [backend/app/db/classification/voting/history.py](#backend-app-db-classification-voting-history-py) — 3 definitions
- [backend/app/db/classification/voting/runs.py](#backend-app-db-classification-voting-runs-py) — 1 definition
- [backend/app/db/classification/voting/state.py](#backend-app-db-classification-voting-state-py) — 3 definitions
- [backend/app/db/classification/voting/votes.py](#backend-app-db-classification-voting-votes-py) — 4 definitions
- [backend/app/db/collection/completion.py](#backend-app-db-collection-completion-py) — 4 definitions
- [backend/app/db/collection/job_reads.py](#backend-app-db-collection-job_reads-py) — 5 definitions
- [backend/app/db/collection/jobs.py](#backend-app-db-collection-jobs-py) — 7 definitions
- [backend/app/db/collection/reservations.py](#backend-app-db-collection-reservations-py) — 4 definitions
- [backend/app/db/collection/traces/reading.py](#backend-app-db-collection-traces-reading-py) — 1 definition
- [backend/app/db/collection/traces/sanitization.py](#backend-app-db-collection-traces-sanitization-py) — 5 definitions
- [backend/app/db/collection/traces/writing.py](#backend-app-db-collection-traces-writing-py) — 1 definition
- [backend/app/db/connection.py](#backend-app-db-connection-py) — 11 definitions
- [backend/app/db/execution/application_lock.py](#backend-app-db-execution-application_lock-py) — 11 definitions
- [backend/app/db/execution/commands.py](#backend-app-db-execution-commands-py) — 4 definitions
- [backend/app/db/execution/quotas.py](#backend-app-db-execution-quotas-py) — 6 definitions
- [backend/app/db/execution/retries.py](#backend-app-db-execution-retries-py) — 1 definition
- [backend/app/db/execution/worker_claims.py](#backend-app-db-execution-worker_claims-py) — 2 definitions
- [backend/app/db/maintenance.py](#backend-app-db-maintenance-py) — 5 definitions
- [backend/app/db/migrations/__init__.py](#backend-app-db-migrations-__init__-py) — 1 definition
- [backend/app/db/migrations/v001.py](#backend-app-db-migrations-v001-py) — 1 definition
- [backend/app/db/owner_ids.py](#backend-app-db-owner_ids-py) — 1 definition
- [backend/app/db/public_history.py](#backend-app-db-public_history-py) — 8 definitions
- [backend/app/db/schema.py](#backend-app-db-schema-py) — 17 definitions
- [backend/app/db/search/admission.py](#backend-app-db-search-admission-py) — 1 definition
- [backend/app/db/search/completion.py](#backend-app-db-search-completion-py) — 5 definitions
- [backend/app/db/search/jobs.py](#backend-app-db-search-jobs-py) — 5 definitions
- [backend/app/db/search/progress.py](#backend-app-db-search-progress-py) — 1 definition
- [backend/app/db/search/sessions.py](#backend-app-db-search-sessions-py) — 3 definitions
- [backend/app/db/serialization.py](#backend-app-db-serialization-py) — 15 definitions
- [backend/app/lifecycle.py](#backend-app-lifecycle-py) — 3 definitions
- [backend/app/main.py](#backend-app-main-py) — 4 definitions
- [backend/app/migrate.py](#backend-app-migrate-py) — 2 definitions
- [backend/app/policies/quotas.py](#backend-app-policies-quotas-py) — 9 definitions
- [backend/app/policies/retries.py](#backend-app-policies-retries-py) — 5 definitions
- [backend/app/workers/classification/worker.py](#backend-app-workers-classification-worker-py) — 8 definitions
- [backend/app/workers/collection/worker.py](#backend-app-workers-collection-worker-py) — 7 definitions
- [backend/app/workers/contracts.py](#backend-app-workers-contracts-py) — 5 definitions
- [backend/app/workers/failures.py](#backend-app-workers-failures-py) — 2 definitions
- [backend/app/workers/runtime.py](#backend-app-workers-runtime-py) — 5 definitions
- [backend/app/workers/search/discovery.py](#backend-app-workers-search-discovery-py) — 9 definitions
- [backend/app/workers/search/worker.py](#backend-app-workers-search-worker-py) — 4 definitions
- [backend/app/workers/sql_retries.py](#backend-app-workers-sql_retries-py) — 2 definitions
- [backend/app/workers/state.py](#backend-app-workers-state-py) — 6 definitions
- [backend/app/workers/stores.py](#backend-app-workers-stores-py) — 6 definitions
- [backend/container_entrypoint.py](#backend-container_entrypoint-py) — 3 definitions
- [browser/container_entrypoint.py](#browser-container_entrypoint-py) — 1 definition
- [browser/public_proxy.py](#browser-public_proxy-py) — 6 definitions
- [collector/budget.py](#collector-budget-py) — 12 definitions
- [collector/classification/checkpoints.py](#collector-classification-checkpoints-py) — 4 definitions
- [collector/classification/ensemble.py](#collector-classification-ensemble-py) — 24 definitions
- [collector/classification/factory.py](#collector-classification-factory-py) — 4 definitions
- [collector/classification/llm_client.py](#collector-classification-llm_client-py) — 10 definitions
- [collector/classification/page.py](#collector-classification-page-py) — 2 definitions
- [collector/classification/page_llm_classifier.py](#collector-classification-page_llm_classifier-py) — 7 definitions
- [collector/classification/prompts.py](#collector-classification-prompts-py) — 7 definitions
- [collector/classification/providers/epfl_rcp.py](#collector-classification-providers-epfl_rcp-py) — 2 definitions
- [collector/classification/repository.py](#collector-classification-repository-py) — 5 definitions
- [collector/classification/repository_llm_classifier.py](#collector-classification-repository_llm_classifier-py) — 8 definitions
- [collector/classification/voting.py](#collector-classification-voting-py) — 2 definitions
- [collector/collection/browser.py](#collector-collection-browser-py) — 8 definitions
- [collector/collection/compatibility.py](#collector-collection-compatibility-py) — 1 definition
- [collector/collection/connectors/__init__.py](#collector-collection-connectors-__init__-py) — 5 definitions
- [collector/collection/connectors/dataverse.py](#collector-collection-connectors-dataverse-py) — 6 definitions
- [collector/collection/connectors/dryad.py](#collector-collection-connectors-dryad-py) — 7 definitions
- [collector/collection/connectors/dspace.py](#collector-collection-connectors-dspace-py) — 10 definitions
- [collector/collection/connectors/figshare.py](#collector-collection-connectors-figshare-py) — 6 definitions
- [collector/collection/connectors/inveniordm.py](#collector-collection-connectors-inveniordm-py) — 8 definitions
- [collector/collection/connectors/metadata.py](#collector-collection-connectors-metadata-py) — 8 definitions
- [collector/collection/connectors/shared.py](#collector-collection-connectors-shared-py) — 3 definitions
- [collector/collection/connectors/zenodo.py](#collector-collection-connectors-zenodo-py) — 7 definitions
- [collector/collection/contracts.py](#collector-collection-contracts-py) — 1 definition
- [collector/collection/failures.py](#collector-collection-failures-py) — 1 definition
- [collector/collection/http.py](#collector-collection-http-py) — 3 definitions
- [collector/collection/orchestrator.py](#collector-collection-orchestrator-py) — 4 definitions
- [collector/collection/pipeline.py](#collector-collection-pipeline-py) — 7 definitions
- [collector/collection/records.py](#collector-collection-records-py) — 1 definition
- [collector/collection/registry.py](#collector-collection-registry-py) — 3 definitions
- [collector/collection/resources.py](#collector-collection-resources-py) — 1 definition
- [collector/collection/service.py](#collector-collection-service-py) — 6 definitions
- [collector/collection/strategies/dataverse.py](#collector-collection-strategies-dataverse-py) — 2 definitions
- [collector/config.py](#collector-config-py) — 5 definitions
- [collector/diagnostics.py](#collector-diagnostics-py) — 8 definitions
- [collector/discovery/adapters/__init__.py](#collector-discovery-adapters-__init__-py) — 1 definition
- [collector/discovery/adapters/ckan.py](#collector-discovery-adapters-ckan-py) — 10 definitions
- [collector/discovery/adapters/data_json.py](#collector-discovery-adapters-data_json-py) — 14 definitions
- [collector/discovery/adapters/generic.py](#collector-discovery-adapters-generic-py) — 3 definitions
- [collector/discovery/adapters/shared.py](#collector-discovery-adapters-shared-py) — 25 definitions
- [collector/discovery/adapters/socrata.py](#collector-discovery-adapters-socrata-py) — 10 definitions
- [collector/discovery/manager.py](#collector-discovery-manager-py) — 1 definition
- [collector/discovery/sitemap.py](#collector-discovery-sitemap-py) — 12 definitions
- [collector/execution.py](#collector-execution-py) — 9 definitions
- [collector/extraction/dataset_metadata.py](#collector-extraction-dataset_metadata-py) — 4 definitions
- [collector/extraction/distributions.py](#collector-extraction-distributions-py) — 8 definitions
- [collector/extraction/errors.py](#collector-extraction-errors-py) — 1 definition
- [collector/extraction/extractor.py](#collector-extraction-extractor-py) — 38 definitions
- [collector/extraction/graph.py](#collector-extraction-graph-py) — 9 definitions
- [collector/extraction/limits.py](#collector-extraction-limits-py) — 5 definitions
- [collector/extraction/source_identity.py](#collector-extraction-source_identity-py) — 2 definitions
- [collector/network/fetch.py](#collector-network-fetch-py) — 15 definitions
- [collector/network/policy.py](#collector-network-policy-py) — 1 definition
- [collector/network/resolver.py](#collector-network-resolver-py) — 3 definitions
- [collector/network/transport.py](#collector-network-transport-py) — 20 definitions
- [collector/observability.py](#collector-observability-py) — 5 definitions
- [collector/repository_search/filtering.py](#collector-repository_search-filtering-py) — 4 definitions
- [collector/repository_search/models.py](#collector-repository_search-models-py) — 1 definition
- [collector/repository_search/providers/datacite.py](#collector-repository_search-providers-datacite-py) — 27 definitions
- [collector/repository_search/service.py](#collector-repository_search-service-py) — 5 definitions
- [collector/storage/metadata.py](#collector-storage-metadata-py) — 3 definitions
- [collector/storage/models.py](#collector-storage-models-py) — 6 definitions
- [collector/url_utils.py](#collector-url_utils-py) — 5 definitions
- [collector/validation/distributions.py](#collector-validation-distributions-py) — 19 definitions
- [collector/validation/json_sample.py](#collector-validation-json_sample-py) — 6 definitions
- [scripts/api_client.py](#scripts-api_client-py) — 41 definitions
- [scripts/setup_api.py](#scripts-setup_api-py) — 8 definitions
- [scripts/start_api.py](#scripts-start_api-py) — 3 definitions
- [search_lab/backend/app.py](#search_lab-backend-app-py) — 13 definitions
- [search_lab/backend/attempts.py](#search_lab-backend-attempts-py) — 1 definition
- [search_lab/backend/comparison.py](#search_lab-backend-comparison-py) — 2 definitions
- [search_lab/backend/history.py](#search_lab-backend-history-py) — 9 definitions
- [search_lab/backend/settings.py](#search_lab-backend-settings-py) — 3 definitions
- [search_lab/backend/snapshots.py](#search_lab-backend-snapshots-py) — 7 definitions
- [search_lab/scenarios/experiment.py](#search_lab-scenarios-experiment-py) — 2 definitions
- [search_lab/scenarios/run.py](#search_lab-scenarios-run-py) — 4 definitions

<a id="backend-app-api-middleware-py"></a>

## backend/app/api/middleware.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`configured_max_request_body_bytes`](../../backend/app/api/middleware.py#L16) | `configured_max_request_body_bytes() -> int` | function / method |
| [`configured_request_body_timeout_seconds`](../../backend/app/api/middleware.py#L28) | `configured_request_body_timeout_seconds() -> float` | function / method |
| [`RequestBodyLimitMiddleware.__init__`](../../backend/app/api/middleware.py#L47) | `__init__(self, app: ASGIApp, *, max_body_bytes: int \| None=None, body_timeout_seconds: float \| None=None) -> None` | function / method |
| [`RequestBodyLimitMiddleware.__call__`](../../backend/app/api/middleware.py#L60) | `__call__(self, scope: Scope, receive: Receive, send: Send) -> None` | async |
| [`RequestBodyLimitMiddleware.__call__.<local>.replay`](../../backend/app/api/middleware.py#L103) | `replay() -> Message` | async |
| [`RequestBodyLimitMiddleware._reject`](../../backend/app/api/middleware.py#L112) | `_reject(scope: Scope, receive: Receive, send: Send) -> None` | staticmethod |
| [`ApplicationAvailabilityMiddleware.__init__`](../../backend/app/api/middleware.py#L123) | `__init__(self, app: ASGIApp)` | function / method |
| [`ApplicationAvailabilityMiddleware.__call__`](../../backend/app/api/middleware.py#L126) | `__call__(self, scope: Scope, receive: Receive, send: Send) -> None` | async |

<a id="backend-app-api-presenters-catalog-py"></a>

## backend/app/api/presenters/catalog.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_build_dataset_distribution_view`](../../backend/app/api/presenters/catalog.py#L14) | `_build_dataset_distribution_view(distribution: DistributionCandidate) -> DatasetDistributionView` | function / method |
| [`_build_distribution_validation_view`](../../backend/app/api/presenters/catalog.py#L30) | `_build_distribution_validation_view(validation: ValidationResult) -> DistributionValidationView` | function / method |
| [`build_catalog_dataset_view`](../../backend/app/api/presenters/catalog.py#L50) | `build_catalog_dataset_view(dataset: CollectedDataset) -> CatalogDatasetView` | function / method |

<a id="backend-app-api-presenters-classification-py"></a>

## backend/app/api/presenters/classification.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_sanitize_ensemble_failures`](../../backend/app/api/presenters/classification.py#L11) | `_sanitize_ensemble_failures(ensemble: dict[str, Any]) -> dict[str, Any]` | function / method |
| [`build_candidate_classification_view`](../../backend/app/api/presenters/classification.py#L37) | `build_candidate_classification_view(classification: dict[str, Any] \| None) -> CandidateClassificationView \| None` | function / method |
| [`prepare_public_dataset_signals`](../../backend/app/api/presenters/classification.py#L48) | `prepare_public_dataset_signals(signals: dict[str, Any]) -> dict[str, Any]` | function / method |

<a id="backend-app-api-presenters-collection-py"></a>

## backend/app/api/presenters/collection.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`build_collection_job_view`](../../backend/app/api/presenters/collection.py#L13) | `build_collection_job_view(job: dict[str, Any]) -> CollectionJobView` | function / method |
| [`build_collection_follow_up_view`](../../backend/app/api/presenters/collection.py#L75) | `build_collection_follow_up_view(collection: CollectionJobReservation \| None) -> CollectionFollowUpView` | function / method |

<a id="backend-app-api-presenters-search-py"></a>

## backend/app/api/presenters/search.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`summarize_search`](../../backend/app/api/presenters/search.py#L31) | `summarize_search(search: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> SearchSummary` | function / method |
| [`_build_repository_candidate_view`](../../backend/app/api/presenters/search.py#L144) | `_build_repository_candidate_view(candidate: dict[str, object], *, automatic_collection: CollectionFollowUpView \| None=None) -> RepositoryCandidateView` | function / method |
| [`build_search_progress_response`](../../backend/app/api/presenters/search.py#L187) | `build_search_progress_response(search_id, snapshot) -> SearchProgressResponse` | function / method |

<a id="backend-app-api-routes-catalog-py"></a>

## backend/app/api/routes/catalog.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`get_catalog_datasets_by_id`](../../backend/app/api/routes/catalog.py#L20) | `get_catalog_datasets_by_id(ids: Annotated[list[Annotated[int, Query(ge=1, le=2147483647)]], Query(min_length=1, max_length=100)]) -> CatalogDatasetsResponse` | async |

<a id="backend-app-api-routes-diagnostics-py"></a>

## backend/app/api/routes/diagnostics.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`get_search_diagnostics`](../../backend/app/api/routes/diagnostics.py#L23) | `get_search_diagnostics(search_id: UUID, principal: Annotated[APIPrincipal, Depends(require_api_principal)], response: Response)` | async |

<a id="backend-app-api-routes-searches-py"></a>

## backend/app/api/routes/searches.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`create_search`](../../backend/app/api/routes/searches.py#L85) | `create_search(payload: SearchCreateRequest, principal: Annotated[APIPrincipal, Depends(require_api_principal)], response: Response, idempotency_key: CommandKey, request: Request) -> SearchSubmissionResponse` | async |
| [`_admit_search_command`](../../backend/app/api/routes/searches.py#L105) | `_admit_search_command(payload, principal, response, idempotency_key, request)` | async |
| [`_build_search_submission_response`](../../backend/app/api/routes/searches.py#L128) | `_build_search_submission_response(row, replayed, principal, response, request)` | async |
| [`get_latest_search`](../../backend/app/api/routes/searches.py#L149) | `get_latest_search(principal: Annotated[APIPrincipal, Depends(require_api_principal)], response: Response, with_candidates: bool=False) -> SearchProgressResponse` | async |
| [`get_search_progress`](../../backend/app/api/routes/searches.py#L174) | `get_search_progress(search_id: UUID, principal: Annotated[APIPrincipal, Depends(require_api_principal)], response: Response) -> SearchProgressResponse` | async |

<a id="backend-app-api-routes-sessions-py"></a>

## backend/app/api/routes/sessions.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ensure_visitor_session`](../../backend/app/api/routes/sessions.py#L15) | `ensure_visitor_session(request: Request) -> Response` | async |

<a id="backend-app-api-schemas-classification-py"></a>

## backend/app/api/schemas/classification.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ClassificationVoteView.validate_decision`](../../backend/app/api/schemas/classification.py#L44) | `validate_decision(self) -> ClassificationVoteView` | function / method |
| [`CandidateClassificationView.validate_decision`](../../backend/app/api/schemas/classification.py#L121) | `validate_decision(self) -> CandidateClassificationView` | function / method |

<a id="backend-app-api-schemas-search-py"></a>

## backend/app/api/schemas/search.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RepositoryCandidateView.validate_metadata_size`](../../backend/app/api/schemas/search.py#L74) | `validate_metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]` | classmethod |

<a id="backend-app-api-search_progress-py"></a>

## backend/app/api/search_progress.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`load_search_progress`](../../backend/app/api/search_progress.py#L17) | `load_search_progress(search_id: UUID, owner_id: str) -> SearchProgressResponse` | async |

<a id="backend-app-auth-security-py"></a>

## backend/app/auth/security.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`validate_api_security_configuration`](../../backend/app/auth/security.py#L63) | `validate_api_security_configuration() -> None` | function / method |
| [`require_api_principal`](../../backend/app/auth/security.py#L72) | `require_api_principal(request: Request, response: Response, visitor_cookie: Annotated[str \| None, Depends(_visitor_scheme)]=None, http_cookie: Annotated[str \| None, Depends(_http_visitor_scheme)]=None) -> APIPrincipal` | async |
| [`enforce_api_quota`](../../backend/app/auth/security.py#L108) | `enforce_api_quota(principal: APIPrincipal, operation: APIQuotaOperation) -> None` | async |
| [`work_admission`](../../backend/app/auth/security.py#L121) | `work_admission(principal: APIPrincipal) -> WorkAdmission` | function / method |
| [`enforce_public_online_quota`](../../backend/app/auth/security.py#L125) | `enforce_public_online_quota(principal: APIPrincipal) -> None` | async |
| [`enforce_session_creation_quota`](../../backend/app/auth/security.py#L131) | `enforce_session_creation_quota(request: Request, settings: VisitorSessionSettings) -> None` | async |
| [`public_client_key`](../../backend/app/auth/security.py#L139) | `public_client_key(request: Request, settings: VisitorSessionSettings) -> str` | function / method |
| [`quota_http_errors`](../../backend/app/auth/security.py#L153) | `quota_http_errors() -> Iterator[None]` | contextmanager |
| [`api_auth_mode`](../../backend/app/auth/security.py#L167) | `api_auth_mode() -> str` | function / method |
| [`require_public_session_bootstrap`](../../backend/app/auth/security.py#L174) | `require_public_session_bootstrap(request: Request) -> VisitorSessionSettings` | function / method |
| [`_require_session_origin`](../../backend/app/auth/security.py#L184) | `_require_session_origin(request: Request, settings: VisitorSessionSettings) -> None` | function / method |
| [`api_cors_origins`](../../backend/app/auth/security.py#L190) | `api_cors_origins() -> list[str]` | function / method |
| [`configure_access_openapi`](../../backend/app/auth/security.py#L211) | `configure_access_openapi(application) -> None` | function / method |
| [`configure_access_openapi.<local>.openapi`](../../backend/app/auth/security.py#L215) | `openapi()` | function / method |

<a id="backend-app-auth-sessions-py"></a>

## backend/app/auth/sessions.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`VisitorSessionSettings.secure`](../../backend/app/auth/sessions.py#L24) | `secure(self) -> bool` | property |
| [`VisitorSessionSettings.cookie_name`](../../backend/app/auth/sessions.py#L28) | `cookie_name(self) -> str` | property |
| [`visitor_session_settings`](../../backend/app/auth/sessions.py#L33) | `visitor_session_settings() -> VisitorSessionSettings` | function / method |
| [`new_visitor_cookie`](../../backend/app/auth/sessions.py#L76) | `new_visitor_cookie(settings: VisitorSessionSettings) -> str` | function / method |
| [`visitor_owner_id`](../../backend/app/auth/sessions.py#L80) | `visitor_owner_id(cookie: str \| None, settings: VisitorSessionSettings) -> str \| None` | function / method |
| [`_serializer`](../../backend/app/auth/sessions.py#L94) | `_serializer(settings: VisitorSessionSettings) -> URLSafeTimedSerializer` | function / method |

<a id="backend-app-db-catalog-datasets-py"></a>

## backend/app/db/catalog/datasets.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`save_collected_datasets`](../../backend/app/db/catalog/datasets.py#L29) | `save_collected_datasets(source_url: str, datasets: list[CollectedDataset], collection_job_id: int \| None=None) -> list[CollectedDataset]` | async |
| [`get_collected_datasets`](../../backend/app/db/catalog/datasets.py#L54) | `get_collected_datasets(dataset_ids: list[int]) -> list[CollectedDataset]` | async |
| [`_datasets_with_distributions`](../../backend/app/db/catalog/datasets.py#L69) | `_datasets_with_distributions(connection, dataset_rows) -> list[CollectedDataset]` | async |
| [`_save_collected_dataset`](../../backend/app/db/catalog/datasets.py#L86) | `_save_collected_dataset(connection: AsyncConnection[DictRow], source_url: str, dataset: CollectedDataset, collection_job_id: int \| None) -> CollectedDataset` | async |
| [`_upsert_collected_dataset`](../../backend/app/db/catalog/datasets.py#L119) | `_upsert_collected_dataset(connection: AsyncConnection[DictRow], source_url: str, dataset: CollectedDataset) -> Row` | async |
| [`_collected_dataset_from_rows`](../../backend/app/db/catalog/datasets.py#L230) | `_collected_dataset_from_rows(dataset_row: Row, distribution_rows: list[Row]) -> CollectedDataset` | function / method |

<a id="backend-app-db-catalog-distributions-py"></a>

## backend/app/db/catalog/distributions.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_validation_results_by_distribution_key`](../../backend/app/db/catalog/distributions.py#L13) | `_validation_results_by_distribution_key(validation_results: list[ValidationResult]) -> dict[tuple[str, str], ValidationResult]` | function / method |
| [`_orphan_validation_result_error`](../../backend/app/db/catalog/distributions.py#L31) | `_orphan_validation_result_error(dataset: CollectedDataset, validation_keys: set[tuple[str, str]]) -> ValueError \| None` | function / method |
| [`_upsert_collected_distributions`](../../backend/app/db/catalog/distributions.py#L53) | `_upsert_collected_distributions(connection: AsyncConnection[DictRow], dataset_id: int, dataset: CollectedDataset) -> None` | async |
| [`_upsert_collected_distribution`](../../backend/app/db/catalog/distributions.py#L83) | `_upsert_collected_distribution(connection: AsyncConnection[DictRow], dataset_id: int, distribution: DistributionCandidate, validation: ValidationResult \| None) -> None` | async |
| [`_fetch_collected_distribution_rows`](../../backend/app/db/catalog/distributions.py#L208) | `_fetch_collected_distribution_rows(connection: AsyncConnection[DictRow], dataset_id: int) -> list[Row]` | async |

<a id="backend-app-db-catalog-observations-py"></a>

## backend/app/db/catalog/observations.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`list_dataset_discovery_observations`](../../backend/app/db/catalog/observations.py#L13) | `list_dataset_discovery_observations(dataset_id: int \| None=None) -> list[dict[str, int \| str \| None]]` | async |
| [`_insert_dataset_discovery_observation`](../../backend/app/db/catalog/observations.py#L23) | `_insert_dataset_discovery_observation(connection: AsyncConnection[DictRow], dataset_id: int, source_url: str, discovery_method: str, collection_job_id: int \| None) -> None` | async |
| [`_select_dataset_discovery_observations`](../../backend/app/db/catalog/observations.py#L43) | `_select_dataset_discovery_observations(connection: AsyncConnection[DictRow], dataset_id: int \| None) -> list[Row]` | async |
| [`_dataset_discovery_observation_to_dict`](../../backend/app/db/catalog/observations.py#L64) | `_dataset_discovery_observation_to_dict(row: Row) -> dict[str, int \| str \| None]` | function / method |

<a id="backend-app-db-catalog-search-py"></a>

## backend/app/db/catalog/search.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`normalize_dataset_search_query`](../../backend/app/db/catalog/search.py#L21) | `normalize_dataset_search_query(query: str) -> str` | function / method |
| [`search_collected_datasets`](../../backend/app/db/catalog/search.py#L42) | `search_collected_datasets(query: str, limit: int=10) -> list[CollectedDataset]` | async |

<a id="backend-app-db-classification-candidates-py"></a>

## backend/app/db/classification/candidates.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`save_repository_candidates`](../../backend/app/db/classification/candidates.py#L23) | `save_repository_candidates(search_id: UUID, owner_id: str, candidates: list[RepositorySearchResult]) -> list[dict[str, object]]` | async |
| [`_save_repository_candidates`](../../backend/app/db/classification/candidates.py#L42) | `_save_repository_candidates(connection: AsyncConnection[DictRow], search_id: UUID, owner_id: str, candidates: list[RepositorySearchResult]) -> list[Row]` | async |
| [`_repository_candidate_to_dict`](../../backend/app/db/classification/candidates.py#L112) | `_repository_candidate_to_dict(row: Row) -> dict[str, object]` | function / method |
| [`_required_text`](../../backend/app/db/classification/candidates.py#L154) | `_required_text(value: str, label: str) -> str` | function / method |
| [`_normalized_keywords`](../../backend/app/db/classification/candidates.py#L161) | `_normalized_keywords(values: list[str]) -> list[str]` | function / method |

<a id="backend-app-db-classification-completion-py"></a>

## backend/app/db/classification/completion.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`complete_candidate_classification`](../../backend/app/db/classification/completion.py#L25) | `complete_candidate_classification(candidate_id: UUID, owner_id: str, classification: RepositoryClassification, *, expected_updated_at: datetime \| None=None) -> CandidateClassificationCompletion \| None` | async |

<a id="backend-app-db-classification-jobs-py"></a>

## backend/app/db/classification/jobs.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`claim_candidate_classification`](../../backend/app/db/classification/jobs.py#L28) | `claim_candidate_classification(*, claim_token: UUID \| None=None) -> dict[str, object] \| None` | async |
| [`_complete_candidate_classification`](../../backend/app/db/classification/jobs.py#L79) | `_complete_candidate_classification(connection: AsyncConnection[DictRow], candidate_id: UUID, owner_id: str, classification: RepositoryClassification, *, expected_updated_at: datetime \| None=None) -> dict[str, object] \| None` | async |
| [`fail_candidate_classification`](../../backend/app/db/classification/jobs.py#L121) | `fail_candidate_classification(candidate_id: UUID, owner_id: str, error: str, *, errors: list[dict] \| None=None, expected_updated_at: datetime \| None=None) -> dict[str, object] \| None` | async |
| [`mark_interrupted_candidate_classifications_error`](../../backend/app/db/classification/jobs.py#L163) | `mark_interrupted_candidate_classifications_error() -> int` | async |

<a id="backend-app-db-classification-voting-history-py"></a>

## backend/app/db/classification/voting/history.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`read_candidate_vote_history`](../../backend/app/db/classification/voting/history.py#L11) | `read_candidate_vote_history(candidate_id, owner_id, *, limit=100, offset=0)` | async |
| [`read_collection_vote_history`](../../backend/app/db/classification/voting/history.py#L27) | `read_collection_vote_history(job_id, owner_id, *, limit=100, offset=0)` | async |
| [`_read_vote_history`](../../backend/app/db/classification/voting/history.py#L43) | `_read_vote_history(column, scope_id, *, limit=100, offset=0)` | async |

<a id="backend-app-db-classification-voting-runs-py"></a>

## backend/app/db/classification/voting/runs.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`prepare_vote_run`](../../backend/app/db/classification/voting/runs.py#L14) | `prepare_vote_run(snapshot, *, candidate_id=None, job_id=None, expected_updated_at=None)` | async |

<a id="backend-app-db-classification-voting-state-py"></a>

## backend/app/db/classification/voting/state.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_scope`](../../backend/app/db/classification/voting/state.py#L10) | `_scope(connection, candidate_id, job_id, version)` | async |
| [`_lock_run`](../../backend/app/db/classification/voting/state.py#L35) | `_lock_run(connection, run_id)` | async |
| [`_publish_progress`](../../backend/app/db/classification/voting/state.py#L43) | `_publish_progress(connection, run_id, candidate_id, job_id)` | async |

<a id="backend-app-db-classification-voting-votes-py"></a>

## backend/app/db/classification/voting/votes.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`claim_vote`](../../backend/app/db/classification/voting/votes.py#L17) | `claim_vote(run_id, voter_id, *, candidate_id=None, job_id=None, expected_updated_at=None, token=None)` | async |
| [`_check_vote_retry`](../../backend/app/db/classification/voting/votes.py#L85) | `_check_vote_retry(scope, vote)` | function / method |
| [`finish_vote`](../../backend/app/db/classification/voting/votes.py#L127) | `finish_vote(run_id, voter_id, token, *, response=None, error='', errors=None, candidate_id=None, job_id=None, expected_updated_at=None)` | async |
| [`mark_interrupted_votes_error`](../../backend/app/db/classification/voting/votes.py#L194) | `mark_interrupted_votes_error()` | async |

<a id="backend-app-db-collection-completion-py"></a>

## backend/app/db/collection/completion.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`complete_collection_job`](../../backend/app/db/collection/completion.py#L22) | `complete_collection_job(job_id: int, collection_result: CollectionResult, *, expected_updated_at: datetime \| None=None) -> dict[str, object] \| None` | async |
| [`mark_collection_job_done`](../../backend/app/db/collection/completion.py#L96) | `mark_collection_job_done(job_id: int, saved_count: int, report: CollectionReport \| None=None) -> dict[str, object] \| None` | async |
| [`_mark_collection_job_done`](../../backend/app/db/collection/completion.py#L108) | `_mark_collection_job_done(connection: AsyncConnection[DictRow], job_id: int, saved_count: int, report: CollectionReport) -> dict[str, object] \| None` | async |
| [`_collection_job_done_message`](../../backend/app/db/collection/completion.py#L166) | `_collection_job_done_message(saved_count: int, report: CollectionReport) -> str` | function / method |

<a id="backend-app-db-collection-job_reads-py"></a>

## backend/app/db/collection/job_reads.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`get_collection_job`](../../backend/app/db/collection/job_reads.py#L17) | `get_collection_job(job_id: int) -> dict[str, object] \| None` | async |
| [`get_collection_job_for_owner`](../../backend/app/db/collection/job_reads.py#L26) | `get_collection_job_for_owner(job_id: int, owner_id: str) -> dict[str, object] \| None` | async |
| [`_get_collection_job_row`](../../backend/app/db/collection/job_reads.py#L51) | `_get_collection_job_row(connection, job_id: int) -> Row \| None` | async |
| [`_job_dataset_ids`](../../backend/app/db/collection/job_reads.py#L68) | `_job_dataset_ids(connection, job_id: int) -> list[int]` | async |
| [`_collection_job_to_dict`](../../backend/app/db/collection/job_reads.py#L78) | `_collection_job_to_dict(row: Row) -> dict[str, object]` | function / method |

<a id="backend-app-db-collection-jobs-py"></a>

## backend/app/db/collection/jobs.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`create_collection_job`](../../backend/app/db/collection/jobs.py#L23) | `create_collection_job(source_url: str) -> dict[str, object]` | async |
| [`mark_interrupted_collection_jobs_error`](../../backend/app/db/collection/jobs.py#L35) | `mark_interrupted_collection_jobs_error() -> int` | async |
| [`claim_pending_collection_job`](../../backend/app/db/collection/jobs.py#L74) | `claim_pending_collection_job(*, claim_token: UUID \| None=None) -> dict[str, object] \| None` | async |
| [`_insert_collection_job`](../../backend/app/db/collection/jobs.py#L123) | `_insert_collection_job(connection: AsyncConnection[DictRow], source_url: str, *, kind: str='source', repository_candidate_id: UUID \| None=None) -> Row \| None` | async |
| [`mark_collection_job_running`](../../backend/app/db/collection/jobs.py#L164) | `mark_collection_job_running(job_id: int) -> dict[str, object] \| None` | async |
| [`mark_collection_job_error`](../../backend/app/db/collection/jobs.py#L203) | `mark_collection_job_error(job_id: int, error: str, *, errors: list[dict] \| None=None, expected_updated_at: datetime \| None=None) -> dict[str, object] \| None` | async |
| [`_lock_running_collection_job`](../../backend/app/db/collection/jobs.py#L244) | `_lock_running_collection_job(connection: AsyncConnection[DictRow], job_id: int) -> Row \| None` | async |

<a id="backend-app-db-collection-reservations-py"></a>

## backend/app/db/collection/reservations.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`reserve_repository_candidate_collection_job`](../../backend/app/db/collection/reservations.py#L33) | `reserve_repository_candidate_collection_job(candidate_id: UUID, owner_id: str) -> CollectionJobReservation` | async |
| [`_reserve_repository_candidate_collection_job`](../../backend/app/db/collection/reservations.py#L49) | `_reserve_repository_candidate_collection_job(connection: AsyncConnection[DictRow], candidate_id: UUID, owner_id: str) -> CollectionJobReservation` | async |
| [`_associate_job_candidate`](../../backend/app/db/collection/reservations.py#L171) | `_associate_job_candidate(connection: AsyncConnection[DictRow], job_id: int, candidate_id: UUID) -> None` | async |
| [`_existing_dataset_ids`](../../backend/app/db/collection/reservations.py#L184) | `_existing_dataset_ids(connection: AsyncConnection[DictRow], source_url: str) -> list[int]` | async |

<a id="backend-app-db-collection-traces-reading-py"></a>

## backend/app/db/collection/traces/reading.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`read_collection_trace`](../../backend/app/db/collection/traces/reading.py#L22) | `read_collection_trace(job_id, owner_id, *, limit=100, offset=0)` | async |

<a id="backend-app-db-collection-traces-sanitization-py"></a>

## backend/app/db/collection/traces/sanitization.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`safe_url`](../../backend/app/db/collection/traces/sanitization.py#L16) | `safe_url(value)` | function / method |
| [`safe_resource_key`](../../backend/app/db/collection/traces/sanitization.py#L28) | `safe_resource_key(value)` | function / method |
| [`safe_coverage`](../../backend/app/db/collection/traces/sanitization.py#L39) | `safe_coverage(value)` | function / method |
| [`safe_check`](../../backend/app/db/collection/traces/sanitization.py#L57) | `safe_check(value)` | function / method |
| [`safe_observation`](../../backend/app/db/collection/traces/sanitization.py#L83) | `safe_observation(observation)` | function / method |

<a id="backend-app-db-collection-traces-writing-py"></a>

## backend/app/db/collection/traces/writing.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`write_collection_trace`](../../backend/app/db/collection/traces/writing.py#L17) | `write_collection_trace(job_id, claim_version, sequence, observation)` | async |

<a id="backend-app-db-connection-py"></a>

## backend/app/db/connection.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`check_database_readiness`](../../backend/app/db/connection.py#L20) | `check_database_readiness() -> None` | async |
| [`_database_url_from_env`](../../backend/app/db/connection.py#L46) | `_database_url_from_env() -> str` | function / method |
| [`configured_database_timeouts`](../../backend/app/db/connection.py#L56) | `configured_database_timeouts() -> tuple[int, int]` | function / method |
| [`open_database_pool`](../../backend/app/db/connection.py#L78) | `open_database_pool() -> None` | async |
| [`open_database_pool.<local>.configure`](../../backend/app/db/connection.py#L86) | `configure(connection)` | async |
| [`close_database_pool`](../../backend/app/db/connection.py#L106) | `close_database_pool() -> None` | async |
| [`_set_initialized_pool`](../../backend/app/db/connection.py#L117) | `_set_initialized_pool(pool: AsyncConnectionPool[DictRow] \| None) -> None` | function / method |
| [`_require_database_initialized`](../../backend/app/db/connection.py#L122) | `_require_database_initialized() -> None` | function / method |
| [`_require_database_pool`](../../backend/app/db/connection.py#L127) | `_require_database_pool() -> AsyncConnectionPool[DictRow]` | function / method |
| [`_fetchone`](../../backend/app/db/connection.py#L136) | `_fetchone(connection: AsyncConnection[DictRow], sql: str, parameters: QueryParameters=None) -> Row \| None` | async |
| [`_fetchall`](../../backend/app/db/connection.py#L146) | `_fetchall(connection: AsyncConnection[DictRow], sql: str, parameters: QueryParameters=None) -> list[Row]` | async |

<a id="backend-app-db-execution-application_lock-py"></a>

## backend/app/db/execution/application_lock.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ApplicationOwnership.__init__`](../../backend/app/db/execution/application_lock.py#L31) | `__init__(self, connection, key: int, *, probe_timeout: float=2.0)` | function / method |
| [`ApplicationOwnership.healthy`](../../backend/app/db/execution/application_lock.py#L38) | `healthy(self) -> bool` | property |
| [`ApplicationOwnership.require_held`](../../backend/app/db/execution/application_lock.py#L42) | `require_held(self) -> None` | function / method |
| [`ApplicationOwnership._mark_lost`](../../backend/app/db/execution/application_lock.py#L47) | `_mark_lost(self) -> None` | function / method |
| [`ApplicationOwnership.check`](../../backend/app/db/execution/application_lock.py#L54) | `check(self) -> None` | async |
| [`ApplicationOwnership.activate`](../../backend/app/db/execution/application_lock.py#L59) | `activate(self) -> None` | async |
| [`ApplicationOwnership._check_locked`](../../backend/app/db/execution/application_lock.py#L75) | `_check_locked(self) -> None` | async |
| [`require_application_ownership`](../../backend/app/db/execution/application_lock.py#L105) | `require_application_ownership() -> None` | function / method |
| [`fence_worker_claim`](../../backend/app/db/execution/application_lock.py#L111) | `fence_worker_claim(connection) -> None` | async |
| [`application_lock`](../../backend/app/db/execution/application_lock.py#L125) | `application_lock(*, probe_interval: float=1.0, probe_timeout: float=2.0)` | asynccontextmanager |
| [`application_lock.<local>.watch`](../../backend/app/db/execution/application_lock.py#L150) | `watch()` | async |

<a id="backend-app-db-execution-commands-py"></a>

## backend/app/db/execution/commands.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`validate_command_key`](../../backend/app/db/execution/commands.py#L17) | `validate_command_key(key: str) -> str` | function / method |
| [`_fingerprint`](../../backend/app/db/execution/commands.py#L25) | `_fingerprint(operation: str, payload: dict) -> str` | function / method |
| [`read_command`](../../backend/app/db/execution/commands.py#L36) | `read_command(connection, owner_id, key, operation, payload)` | async |
| [`record_command`](../../backend/app/db/execution/commands.py#L51) | `record_command(connection, owner_id, key, operation, payload, result)` | async |

<a id="backend-app-db-execution-quotas-py"></a>

## backend/app/db/execution/quotas.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`consume_api_quota`](../../backend/app/db/execution/quotas.py#L21) | `consume_api_quota(owner_id: str, operation: str, *, limit: int) -> APIQuotaDecision` | async |
| [`consume_quota_limits`](../../backend/app/db/execution/quotas.py#L29) | `consume_quota_limits(quotas: tuple[QuotaLimit, ...]) -> None` | async |
| [`reserve_quota_limits`](../../backend/app/db/execution/quotas.py#L43) | `reserve_quota_limits(connection, quotas: tuple[QuotaLimit, ...], *, amount: int) -> None` | async |
| [`lock_work_admission`](../../backend/app/db/execution/quotas.py#L57) | `lock_work_admission(connection, admission: WorkAdmission \| None) -> None` | async |
| [`reserve_work`](../../backend/app/db/execution/quotas.py#L65) | `reserve_work(connection, admission: WorkAdmission \| None, *, amount: int) -> None` | async |
| [`_consume_quota`](../../backend/app/db/execution/quotas.py#L83) | `_consume_quota(connection, quota: QuotaLimit, *, amount: int) -> APIQuotaDecision` | async |

<a id="backend-app-db-execution-retries-py"></a>

## backend/app/db/execution/retries.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`schedule_llm_retry`](../../backend/app/db/execution/retries.py#L13) | `schedule_llm_retry(item_id, version, diagnostics, *, collection=False)` | async |

<a id="backend-app-db-execution-worker_claims-py"></a>

## backend/app/db/execution/worker_claims.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`read_worker_claim`](../../backend/app/db/execution/worker_claims.py#L18) | `read_worker_claim(connection: AsyncConnection[DictRow], token: UUID, queue: Queue) -> Row \| None` | async |
| [`record_worker_claim`](../../backend/app/db/execution/worker_claims.py#L35) | `record_worker_claim(connection: AsyncConnection[DictRow], token: UUID, queue: Queue, resource_id: object, claim_version: datetime) -> None` | async |

<a id="backend-app-db-maintenance-py"></a>

## backend/app/db/maintenance.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RetentionPolicy.__post_init__`](../../backend/app/db/maintenance.py#L26) | `__post_init__(self) -> None` | function / method |
| [`_retention_operations`](../../backend/app/db/maintenance.py#L61) | `_retention_operations(policy: RetentionPolicy)` | function / method |
| [`maintain_database`](../../backend/app/db/maintenance.py#L178) | `maintain_database(policy: RetentionPolicy \| None=None, *, apply: bool=False, batch_size: int=1000) -> dict` | async |
| [`main`](../../backend/app/db/maintenance.py#L250) | `main() -> None` | function / method |
| [`main.<local>.run`](../../backend/app/db/maintenance.py#L265) | `run()` | async |

<a id="backend-app-db-migrations-__init__-py"></a>

## backend/app/db/migrations/__init__.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`migration_for_version`](../../backend/app/db/migrations/__init__.py#L12) | `migration_for_version(version: int)` | function / method |

<a id="backend-app-db-migrations-v001-py"></a>

## backend/app/db/migrations/v001.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_migrate_0_to_1`](../../backend/app/db/migrations/v001.py#L550) | `_migrate_0_to_1(connection: AsyncConnection[DictRow]) -> None` | async |

<a id="backend-app-db-owner_ids-py"></a>

## backend/app/db/owner_ids.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`validate_owner_id`](../../backend/app/db/owner_ids.py#L6) | `validate_owner_id(owner_id: str) -> str` | function / method |

<a id="backend-app-db-public_history-py"></a>

## backend/app/db/public_history.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`HistoryPage.__post_init__`](../../backend/app/db/public_history.py#L18) | `__post_init__(self) -> None` | function / method |
| [`HistoryPage.metadata`](../../backend/app/db/public_history.py#L24) | `metadata(self, has_more: bool) -> dict` | function / method |
| [`public_label`](../../backend/app/db/public_history.py#L34) | `public_label(value: object, *, maximum: int=200) -> str` | function / method |
| [`public_timestamp`](../../backend/app/db/public_history.py#L41) | `public_timestamp(value: object) -> str \| None` | function / method |
| [`public_identifier`](../../backend/app/db/public_history.py#L54) | `public_identifier(value: object) -> str \| None` | function / method |
| [`bounded_diagnostics`](../../backend/app/db/public_history.py#L61) | `bounded_diagnostics(values: object, *, stage: str='classification') -> list[dict]` | function / method |
| [`PublicVoteAttempt.from_row`](../../backend/app/db/public_history.py#L113) | `from_row(cls, row: dict) -> PublicVoteAttempt` | classmethod |
| [`PublicVoteAttempt.to_dict`](../../backend/app/db/public_history.py#L141) | `to_dict(self) -> dict` | function / method |

<a id="backend-app-db-schema-py"></a>

## backend/app/db/schema.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`init_database`](../../backend/app/db/schema.py#L118) | `init_database() -> None` | async |
| [`validate_database_schema`](../../backend/app/db/schema.py#L126) | `validate_database_schema() -> None` | async |
| [`_apply_schema_migrations`](../../backend/app/db/schema.py#L141) | `_apply_schema_migrations(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_validate_schema_contracts`](../../backend/app/db/schema.py#L172) | `_validate_schema_contracts(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_migration_for_version`](../../backend/app/db/schema.py#L179) | `_migration_for_version(version: int)` | function / method |
| [`_run_schema_migration`](../../backend/app/db/schema.py#L183) | `_run_schema_migration(connection: AsyncConnection[DictRow], source_version: int, target_version: int, migration) -> None` | async |
| [`_assert_database_can_be_initialized`](../../backend/app/db/schema.py#L214) | `_assert_database_can_be_initialized(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_existing_managed_tables`](../../backend/app/db/schema.py#L226) | `_existing_managed_tables(connection: AsyncConnection[DictRow]) -> tuple[str, ...]` | async |
| [`_missing_managed_tables`](../../backend/app/db/schema.py#L236) | `_missing_managed_tables(connection: AsyncConnection[DictRow]) -> tuple[str, ...]` | async |
| [`_assert_current_schema_tables_exist`](../../backend/app/db/schema.py#L246) | `_assert_current_schema_tables_exist(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_assert_current_schema_repository_persistence_exists`](../../backend/app/db/schema.py#L258) | `_assert_current_schema_repository_persistence_exists(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_assert_current_schema_has_no_obsolete_columns`](../../backend/app/db/schema.py#L300) | `_assert_current_schema_has_no_obsolete_columns(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_assert_current_schema_search_index_exists`](../../backend/app/db/schema.py#L322) | `_assert_current_schema_search_index_exists(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_table_exists`](../../backend/app/db/schema.py#L362) | `_table_exists(connection: AsyncConnection[DictRow], table_name: str) -> bool` | async |
| [`_require_current_schema`](../../backend/app/db/schema.py#L381) | `_require_current_schema(connection: AsyncConnection[DictRow]) -> None` | async |
| [`_schema_version`](../../backend/app/db/schema.py#L386) | `_schema_version(connection: AsyncConnection[DictRow]) -> int` | async |
| [`_set_schema_version`](../../backend/app/db/schema.py#L399) | `_set_schema_version(connection: AsyncConnection[DictRow], version: int) -> None` | async |

<a id="backend-app-db-search-admission-py"></a>

## backend/app/db/search/admission.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`admit_search`](../../backend/app/db/search/admission.py#L20) | `admit_search(owner_id: str, key: str, *, query: str='', access_mode: str, client_key: str \| None, retry_search_id: UUID \| None=None)` | async |

<a id="backend-app-db-search-completion-py"></a>

## backend/app/db/search/completion.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`complete_discovery`](../../backend/app/db/search/completion.py#L29) | `complete_discovery(job, result)` | async |
| [`complete_search_session`](../../backend/app/db/search/completion.py#L73) | `complete_search_session(search_id: UUID, owner_id: str, *, origin: SearchOrigin, status: SearchStatus='completed', error: str='', errors: list[dict] \| None=None, local_result_count: int \| None=None, discovery_complete: bool \| None=None, warnings: list[dict] \| None=None, local_dataset_ids: list[int] \| None=None) -> dict[str, object]` | async |
| [`_complete_search_session`](../../backend/app/db/search/completion.py#L111) | `_complete_search_session(connection: AsyncConnection[DictRow], search_id: UUID, owner_id: str, *, origin: SearchOrigin, status: SearchStatus, error: str='', errors: list[dict] \| None=None, local_result_count: int \| None=None, discovery_complete: bool \| None=None, warnings: list[dict] \| None=None) -> Row \| None` | async |
| [`save_local_results`](../../backend/app/db/search/completion.py#L160) | `save_local_results(connection, search_id, dataset_ids)` | async |
| [`complete_search_session_with_repository_candidates`](../../backend/app/db/search/completion.py#L174) | `complete_search_session_with_repository_candidates(search_id: UUID, owner_id: str, candidates: list[RepositorySearchResult], *, status: SearchStatus, errors: list[dict] \| None=None, discovery_complete: bool \| None=None, warnings: list[dict] \| None=None, admission: WorkAdmission \| None=None) -> list[dict[str, object]]` | async |

<a id="backend-app-db-search-jobs-py"></a>

## backend/app/db/search/jobs.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`claim_search`](../../backend/app/db/search/jobs.py#L18) | `claim_search(*, claim_token: UUID \| None=None)` | async |
| [`_lock_attempt`](../../backend/app/db/search/jobs.py#L52) | `_lock_attempt(connection, job)` | async |
| [`reserve_external_search`](../../backend/app/db/search/jobs.py#L63) | `reserve_external_search(job)` | async |
| [`fail_discovery`](../../backend/app/db/search/jobs.py#L84) | `fail_discovery(job, *, origin, error, diagnostics, retry_at=None)` | async |
| [`mark_interrupted_search_sessions_error`](../../backend/app/db/search/jobs.py#L109) | `mark_interrupted_search_sessions_error() -> int` | async |

<a id="backend-app-db-search-progress-py"></a>

## backend/app/db/search/progress.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`read_search_progress`](../../backend/app/db/search/progress.py#L14) | `read_search_progress(search_id: UUID, owner_id: str) -> tuple[Row, list[Row], dict[UUID, CollectionJobReservation]] \| None` | async |

<a id="backend-app-db-search-sessions-py"></a>

## backend/app/db/search/sessions.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`create_search_session`](../../backend/app/db/search/sessions.py#L19) | `create_search_session(query: str, owner_id: str) -> dict[str, object]` | async |
| [`latest_search_id`](../../backend/app/db/search/sessions.py#L46) | `latest_search_id(owner_id, *, with_candidates=False)` | async |
| [`_search_session_to_dict`](../../backend/app/db/search/sessions.py#L67) | `_search_session_to_dict(row: Row) -> dict[str, object]` | function / method |

<a id="backend-app-db-serialization-py"></a>

## backend/app/db/serialization.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_serialize_discovery_methods`](../../backend/app/db/serialization.py#L17) | `_serialize_discovery_methods(discovery_methods: tuple[str, ...]) -> Jsonb` | function / method |
| [`_deserialize_discovery_methods`](../../backend/app/db/serialization.py#L26) | `_deserialize_discovery_methods(value: object) -> list[str]` | function / method |
| [`_serialize_geography`](../../backend/app/db/serialization.py#L39) | `_serialize_geography(geography: tuple[str, ...]) -> Jsonb` | function / method |
| [`_deserialize_geography`](../../backend/app/db/serialization.py#L48) | `_deserialize_geography(value: object) -> list[str]` | function / method |
| [`_serialize_signals`](../../backend/app/db/serialization.py#L61) | `_serialize_signals(signals: dict[str, object]) -> Jsonb` | function / method |
| [`_deserialize_signals`](../../backend/app/db/serialization.py#L73) | `_deserialize_signals(value: object, field_name: str='signals') -> dict[str, object]` | function / method |
| [`_jsonb`](../../backend/app/db/serialization.py#L99) | `_jsonb(value: object) -> Jsonb` | function / method |
| [`_json_dumps`](../../backend/app/db/serialization.py#L108) | `_json_dumps(value: object) -> str` | function / method |
| [`_deserialize_json_array`](../../backend/app/db/serialization.py#L112) | `_deserialize_json_array(value: object, field_name: str, field_label: str) -> list[object]` | function / method |
| [`_normalize_string_items_for_storage`](../../backend/app/db/serialization.py#L138) | `_normalize_string_items_for_storage(value: tuple[str, ...], item_label: str) -> list[str]` | function / method |
| [`_normalize_string_items_from_storage`](../../backend/app/db/serialization.py#L154) | `_normalize_string_items_from_storage(value: list[object], field_name: str, field_label: str) -> list[str]` | function / method |
| [`_normalize_string_items`](../../backend/app/db/serialization.py#L165) | `_normalize_string_items(value: list[object], error_prefix: str) -> list[str]` | function / method |
| [`_assert_json_object_keys_are_strings`](../../backend/app/db/serialization.py#L195) | `_assert_json_object_keys_are_strings(value: object, path: str) -> None` | function / method |
| [`_format_timestamp`](../../backend/app/db/serialization.py#L211) | `_format_timestamp(value: object) -> str` | function / method |
| [`_format_optional_timestamp`](../../backend/app/db/serialization.py#L226) | `_format_optional_timestamp(value: object) -> str` | function / method |

<a id="backend-app-lifecycle-py"></a>

## backend/app/lifecycle.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`migrate_on_startup`](../../backend/app/lifecycle.py#L44) | `migrate_on_startup() -> bool` | function / method |
| [`lifespan`](../../backend/app/lifecycle.py#L51) | `lifespan(application: FastAPI) -> AsyncIterator[None]` | asynccontextmanager |
| [`_watch_ownership`](../../backend/app/lifecycle.py#L114) | `_watch_ownership(application, ownership) -> None` | async |

<a id="backend-app-main-py"></a>

## backend/app/main.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`database_timeout`](../../backend/app/main.py#L30) | `database_timeout(request, exception) -> JSONResponse` | async |
| [`health`](../../backend/app/main.py#L38) | `health() -> dict[str, str]` | function / method |
| [`ready`](../../backend/app/main.py#L42) | `ready(request: Request) -> JSONResponse` | async |
| [`create_app`](../../backend/app/main.py#L70) | `create_app() -> FastAPI` | function / method |

<a id="backend-app-migrate-py"></a>

## backend/app/migrate.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`run_migrations`](../../backend/app/migrate.py#L15) | `run_migrations(*, check_only: bool=False) -> None` | async |
| [`main`](../../backend/app/migrate.py#L27) | `main() -> int` | function / method |

<a id="backend-app-policies-quotas-py"></a>

## backend/app/policies/quotas.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`QuotaExceeded.__init__`](../../backend/app/policies/quotas.py#L26) | `__init__(self, retry_after_seconds: int, message: str='API request quota exceeded.')` | function / method |
| [`owner_quota`](../../backend/app/policies/quotas.py#L50) | `owner_quota(owner_id: str, operation: str) -> QuotaLimit` | function / method |
| [`public_ip_quota`](../../backend/app/policies/quotas.py#L54) | `public_ip_quota(client_key: str, operation: str) -> QuotaLimit` | function / method |
| [`public_daily_quota`](../../backend/app/policies/quotas.py#L58) | `public_daily_quota(operation: Literal['online_daily', 'work_daily']) -> QuotaLimit` | function / method |
| [`classification_admission`](../../backend/app/policies/quotas.py#L62) | `classification_admission(owner_id: str, client_key: str \| None) -> WorkAdmission` | function / method |
| [`validate_quota_configuration`](../../backend/app/policies/quotas.py#L74) | `validate_quota_configuration(*, public: bool) -> None` | function / method |
| [`_limit`](../../backend/app/policies/quotas.py#L83) | `_limit(name: str, default: int, *, maximum: int=1000000) -> int` | function / method |
| [`search_command_quotas`](../../backend/app/policies/quotas.py#L93) | `search_command_quotas(owner_id: str, client_key: str \| None) -> tuple[QuotaLimit, ...]` | function / method |
| [`search_queue_capacity`](../../backend/app/policies/quotas.py#L100) | `search_queue_capacity() -> int` | function / method |

<a id="backend-app-policies-retries-py"></a>

## backend/app/policies/retries.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RetryPolicy.configured`](../../backend/app/policies/retries.py#L23) | `configured(cls)` | classmethod |
| [`RetryPolicy.limit`](../../backend/app/policies/retries.py#L40) | `limit(self, code)` | function / method |
| [`as_datetime`](../../backend/app/policies/retries.py#L50) | `as_datetime(value)` | function / method |
| [`enforce_retry_date`](../../backend/app/policies/retries.py#L57) | `enforce_retry_date(errors, *, now=None)` | function / method |
| [`plan_retry`](../../backend/app/policies/retries.py#L66) | `plan_retry(errors: list[Diagnostic], *, round_number, started_at, now=None, policy=None)` | function / method |

<a id="backend-app-workers-classification-worker-py"></a>

## backend/app/workers/classification/worker.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_classify`](../../backend/app/workers/classification/worker.py#L29) | `_classify(candidate: ClassificationJob, vote_store: VoteStore) -> RepositoryClassification \| None` | function / method |
| [`ClassificationWorker.__init__`](../../backend/app/workers/classification/worker.py#L45) | `__init__(self, *, classify: Callable[[ClassificationJob, VoteStore], RepositoryClassification \| None] \| None=None, vote_store_factory: Callable[..., VoteStore] \| None=None, persist: Persistence \| None=None) -> None` | function / method |
| [`ClassificationWorker.claim`](../../backend/app/workers/classification/worker.py#L65) | `claim(self, *, claim_token: UUID) -> ClassificationJob \| None` | async |
| [`ClassificationWorker.execute`](../../backend/app/workers/classification/worker.py#L68) | `execute(self, candidate: ClassificationJob, executor: Executor) -> None` | async |
| [`ClassificationWorker._retry`](../../backend/app/workers/classification/worker.py#L108) | `_retry(self, candidate: ClassificationJob, diagnostics: list[Diagnostic]) -> tuple[bool, list[Diagnostic]]` | async |
| [`ClassificationWorker._fail`](../../backend/app/workers/classification/worker.py#L120) | `_fail(self, candidate: ClassificationJob, error: str, diagnostics: list[Diagnostic]) -> object` | async |
| [`ClassificationWorker.recover`](../../backend/app/workers/classification/worker.py#L134) | `recover(self, candidate: ClassificationJob) -> object` | async |
| [`_repository_search_result_from_candidate`](../../backend/app/workers/classification/worker.py#L143) | `_repository_search_result_from_candidate(candidate: ClassificationJob) -> RepositorySearchResult` | function / method |

<a id="backend-app-workers-collection-worker-py"></a>

## backend/app/workers/collection/worker.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_collect_record_job`](../../backend/app/workers/collection/worker.py#L43) | `_collect_record_job(url, *, classifier, observe)` | function / method |
| [`CollectionWorker.__init__`](../../backend/app/workers/collection/worker.py#L75) | `__init__(self, *, classifier_factory: Callable[..., PageClassifier] \| None=None, vote_store_factory: Callable[..., VoteStore] \| None=None, trace_factory: Callable[..., PostgresCollectionTraceWriter] \| None=None, collect_source: Callable[..., CollectionResult] \| None=None, collect_record: Callable[..., CollectionResult] \| None=None, persist: Persistence \| None=None) -> None` | function / method |
| [`CollectionWorker.claim`](../../backend/app/workers/collection/worker.py#L106) | `claim(self, *, claim_token: UUID) -> CollectionJob \| None` | async |
| [`CollectionWorker.execute`](../../backend/app/workers/collection/worker.py#L109) | `execute(self, job: CollectionJob, executor: Executor) -> None` | async |
| [`CollectionWorker._retry`](../../backend/app/workers/collection/worker.py#L155) | `_retry(self, job: CollectionJob, diagnostics: list[Diagnostic]) -> tuple[bool, list[Diagnostic]]` | async |
| [`CollectionWorker._fail`](../../backend/app/workers/collection/worker.py#L167) | `_fail(self, job: CollectionJob, error: str, diagnostics: list[Diagnostic]) -> object` | async |
| [`CollectionWorker.recover`](../../backend/app/workers/collection/worker.py#L180) | `recover(self, job: CollectionJob) -> object` | async |

<a id="backend-app-workers-contracts-py"></a>

## backend/app/workers/contracts.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`Worker.name`](../../backend/app/workers/contracts.py#L17) | `name(self) -> str` | property |
| [`Worker.claim`](../../backend/app/workers/contracts.py#L20) | `claim(self, *, claim_token: UUID) -> JobT \| None` | async |
| [`Worker.execute`](../../backend/app/workers/contracts.py#L24) | `execute(self, job: JobT, executor: Executor) -> None` | async |
| [`Worker.recover`](../../backend/app/workers/contracts.py#L28) | `recover(self, job: JobT) -> object` | async |
| [`Persistence.__call__`](../../backend/app/workers/contracts.py#L36) | `__call__(self, operation: Callable[[], Awaitable[ResultT]], *, retry_storage_failures: bool=False, retry_unexpected: bool=False) -> ResultT` | async |

<a id="backend-app-workers-failures-py"></a>

## backend/app/workers/failures.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`FailureHandler.__init__`](../../backend/app/workers/failures.py#L26) | `__init__(self, *, stage: Stage, retry: RetryCallback[JobT], fail: FailureCallback[JobT], persist: Persistence \| None=None) -> None` | function / method |
| [`FailureHandler.handle`](../../backend/app/workers/failures.py#L39) | `handle(self, job: JobT, exception: Exception, *, saving: bool) -> None` | async |

<a id="backend-app-workers-runtime-py"></a>

## backend/app/workers/runtime.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`configured_worker_shutdown_seconds`](../../backend/app/workers/runtime.py#L29) | `configured_worker_shutdown_seconds() -> float` | function / method |
| [`worker_shutdown_budget`](../../backend/app/workers/runtime.py#L36) | `worker_shutdown_budget(*, seconds: float \| None=None) -> AsyncIterator[None]` | asynccontextmanager |
| [`_consume`](../../backend/app/workers/runtime.py#L49) | `_consume(stop: asyncio.Event, executor: Executor, poll_interval: float, worker: Worker[JobT]) -> None` | async |
| [`persisted_workers`](../../backend/app/workers/runtime.py#L99) | `persisted_workers(worker: Worker[JobT], *, concurrency: int, poll_interval: float=1.0, shutdown_timeout: float \| None=None) -> AsyncIterator[None]` | asynccontextmanager |
| [`persisted_workers.<local>.run`](../../backend/app/workers/runtime.py#L126) | `run(state: WorkerState) -> None` | async |

<a id="backend-app-workers-search-discovery-py"></a>

## backend/app/workers/search/discovery.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RepositoryResultBounder.__call__`](../../backend/app/workers/search/discovery.py#L53) | `__call__(self, item: RepositorySearchResult, *, search_query: str) -> RepositorySearchResult` | function / method |
| [`DiscoveryResult.complete`](../../backend/app/workers/search/discovery.py#L75) | `complete(self) -> bool` | property |
| [`DiscoveryResult.diagnostics`](../../backend/app/workers/search/discovery.py#L80) | `diagnostics(self) -> list[dict[str, object]]` | property |
| [`DiscoveryResult.warning_records`](../../backend/app/workers/search/discovery.py#L90) | `warning_records(self) -> list[SearchWarningRecord]` | property |
| [`lookup_local`](../../backend/app/workers/search/discovery.py#L104) | `lookup_local(query: str, *, lookup: Callable[[str], Awaitable[list[CollectedDataset]]]=search_collected_datasets) -> list[CollectedDataset]` | async |
| [`_bounded_repository_result`](../../backend/app/workers/search/discovery.py#L119) | `_bounded_repository_result(item: RepositorySearchResult, *, search_query: str) -> RepositorySearchResult` | function / method |
| [`_bounded_repository_metadata`](../../backend/app/workers/search/discovery.py#L144) | `_bounded_repository_metadata(value: object) -> dict[str, str]` | function / method |
| [`_json_size_bytes`](../../backend/app/workers/search/discovery.py#L169) | `_json_size_bytes(value: dict[str, str]) -> int` | function / method |
| [`prepare_repository_candidates`](../../backend/app/workers/search/discovery.py#L181) | `prepare_repository_candidates(response: RepositorySearchResponse, query: str, admission: WorkAdmission, *, bound: RepositoryResultBounder=_bounded_repository_result) -> DiscoveryResult` | function / method |

<a id="backend-app-workers-search-worker-py"></a>

## backend/app/workers/search/worker.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`SearchWorker.__init__`](../../backend/app/workers/search/worker.py#L34) | `__init__(self, *, local_lookup: Callable[[str], Awaitable[list[CollectedDataset]]] \| None=None, provider: Callable[[str], RepositorySearchResponse] \| None=None, persist: Persistence \| None=None) -> None` | function / method |
| [`SearchWorker.claim`](../../backend/app/workers/search/worker.py#L45) | `claim(self, *, claim_token: UUID) -> SearchJob \| None` | async |
| [`SearchWorker.execute`](../../backend/app/workers/search/worker.py#L49) | `execute(self, job: SearchJob, executor: Executor) -> None` | async |
| [`SearchWorker.recover`](../../backend/app/workers/search/worker.py#L117) | `recover(self, job: SearchJob) -> object` | async |

<a id="backend-app-workers-sql_retries-py"></a>

## backend/app/workers/sql_retries.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_retryable`](../../backend/app/workers/sql_retries.py#L25) | `_retryable(exception: Exception, *, retry_storage_failures: bool) -> bool` | function / method |
| [`persist_with_retry`](../../backend/app/workers/sql_retries.py#L35) | `persist_with_retry(operation: Callable[[], Awaitable[T]], *, initial_delay: float=1.0, max_delay: float=30.0, log_operation: bool=True, stop: asyncio.Event \| None=None, retry_storage_failures: bool=False, retry_unexpected: bool=False, event_sink=emit_event) -> T` | async |

<a id="backend-app-workers-state-py"></a>

## backend/app/workers/state.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ShutdownBudget.start`](../../backend/app/workers/state.py#L17) | `start(self) -> None` | function / method |
| [`WorkerState.persistence_blocked`](../../backend/app/workers/state.py#L36) | `persistence_blocked(self) -> bool` | property |
| [`workers_ready`](../../backend/app/workers/state.py#L45) | `workers_ready() -> bool` | function / method |
| [`request_worker_stop`](../../backend/app/workers/state.py#L52) | `request_worker_stop(*, force: bool=False) -> None` | function / method |
| [`register_worker`](../../backend/app/workers/state.py#L63) | `register_worker(worker: WorkerState) -> None` | function / method |
| [`unregister_worker`](../../backend/app/workers/state.py#L67) | `unregister_worker(worker: WorkerState) -> None` | function / method |

<a id="backend-app-workers-stores-py"></a>

## backend/app/workers/stores.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_submit_and_wait`](../../backend/app/workers/stores.py#L22) | `_submit_and_wait(loop: asyncio.AbstractEventLoop, coroutine: Coroutine[Any, Any, T]) -> T` | function / method |
| [`PostgresVoteStore.__init__`](../../backend/app/workers/stores.py#L46) | `__init__(self, loop: asyncio.AbstractEventLoop, *, candidate_id: UUID \| None=None, job_id: int \| None=None, expected_updated_at: datetime \| None=None) -> None` | function / method |
| [`PostgresVoteStore._wait`](../../backend/app/workers/stores.py#L61) | `_wait(self, operation: Callable[[], Awaitable[T]], *, finalizing: bool=False) -> T` | function / method |
| [`PostgresVoteStore.run`](../../backend/app/workers/stores.py#L76) | `run(self, snapshot: dict[str, object], voter_id: str, invoke: Callable[[], dict[str, object]]) -> dict[str, object]` | function / method |
| [`PostgresCollectionTraceWriter.__init__`](../../backend/app/workers/stores.py#L128) | `__init__(self, loop: asyncio.AbstractEventLoop, job_id: int, version: datetime) -> None` | function / method |
| [`PostgresCollectionTraceWriter.__call__`](../../backend/app/workers/stores.py#L131) | `__call__(self, sequence: int, observation: dict[str, object]) -> None` | function / method |

<a id="backend-container_entrypoint-py"></a>

## backend/container_entrypoint.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`build_rules`](../../backend/container_entrypoint.py#L15) | `build_rules(database_addresses: list[str], resolver_addresses: list[str], extra: str='', browser_addresses: list[str] \| None=None) -> str` | function / method |
| [`install_egress_rules`](../../backend/container_entrypoint.py#L72) | `install_egress_rules() -> None` | function / method |
| [`main`](../../backend/container_entrypoint.py#L120) | `main() -> None` | function / method |

<a id="browser-container_entrypoint-py"></a>

## browser/container_entrypoint.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`rules`](../../browser/container_entrypoint.py#L13) | `rules(resolvers, extra='')` | function / method |

<a id="browser-public_proxy-py"></a>

## browser/public_proxy.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`BoundedProxyServer.__init__`](../../browser/public_proxy.py#L17) | `__init__(self, *args, **kwargs)` | function / method |
| [`BoundedProxyServer.process_request`](../../browser/public_proxy.py#L21) | `process_request(self, request, client_address)` | function / method |
| [`BoundedProxyServer.process_request_thread`](../../browser/public_proxy.py#L31) | `process_request_thread(self, request, client_address)` | function / method |
| [`PublicProxy.log_message`](../../browser/public_proxy.py#L41) | `log_message(self, *_)` | function / method |
| [`PublicProxy.do_CONNECT`](../../browser/public_proxy.py#L44) | `do_CONNECT(self)` | function / method |
| [`PublicProxy.do_GET`](../../browser/public_proxy.py#L81) | `do_GET(self)` | function / method |

<a id="collector-budget-py"></a>

## collector/budget.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`CollectionBudgetExceeded.__init__`](../../collector/budget.py#L23) | `__init__(self)` | function / method |
| [`CollectionBudget.remaining`](../../collector/budget.py#L36) | `remaining(self) -> float` | function / method |
| [`active_collection_budget`](../../collector/budget.py#L47) | `active_collection_budget() -> CollectionBudget \| None` | function / method |
| [`collection_budget`](../../collector/budget.py#L51) | `collection_budget(*, seconds: float=300, deadline_at: datetime \| str \| None=None)` | contextmanager |
| [`check_collection_budget`](../../collector/budget.py#L71) | `check_collection_budget() -> None` | function / method |
| [`RequestBudget.remaining`](../../collector/budget.py#L84) | `remaining(self) -> float` | function / method |
| [`active_request_budget`](../../collector/budget.py#L95) | `active_request_budget() -> RequestBudget \| None` | function / method |
| [`request_budget`](../../collector/budget.py#L99) | `request_budget(*, seconds: float)` | contextmanager |
| [`cleanup_request_budget`](../../collector/budget.py#L121) | `cleanup_request_budget(*, seconds: float)` | contextmanager |
| [`check_request_budget`](../../collector/budget.py#L136) | `check_request_budget() -> None` | function / method |
| [`remaining_timeout`](../../collector/budget.py#L143) | `remaining_timeout(timeout: float) -> float` | function / method |
| [`read_with_budget`](../../collector/budget.py#L152) | `read_with_budget(response, max_bytes: int) -> bytes` | function / method |

<a id="collector-classification-checkpoints-py"></a>

## collector/classification/checkpoints.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`VoteStore.run`](../../collector/classification/checkpoints.py#L12) | `run(self, snapshot: dict[str, object], voter_id: str, invoke: Callable[[], dict[str, object]]) -> dict[str, object]` | function / method |
| [`CheckpointedLLMClient.__init__`](../../collector/classification/checkpoints.py#L23) | `__init__(self, client: HTTPJSONLLMClient, store: VoteStore, voter_id: str, configuration: list[dict[str, object]], validate: Callable) -> None` | function / method |
| [`CheckpointedLLMClient.classify_payload`](../../collector/classification/checkpoints.py#L37) | `classify_payload(self, payload: dict[str, object]) -> dict[str, object]` | function / method |
| [`CheckpointedLLMClient.classify_payload.<local>.invoke`](../../collector/classification/checkpoints.py#L40) | `invoke()` | function / method |

<a id="collector-classification-ensemble-py"></a>

## collector/classification/ensemble.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_validate_voting_thresholds`](../../collector/classification/ensemble.py#L30) | `_validate_voting_thresholds(*, voter_count: int, votes_required: int, minimum_successful_votes: int \| None) -> int` | function / method |
| [`EnsemblePageClassifier.__init__`](../../collector/classification/ensemble.py#L65) | `__init__(self, voters: list[tuple[str, PageClassifier]] \| tuple[tuple[str, PageClassifier], ...], votes_required: int=2, minimum_successful_votes: int \| None=None) -> None` | function / method |
| [`EnsemblePageClassifier.voter_ids`](../../collector/classification/ensemble.py#L87) | `voter_ids(self) -> tuple[str, ...]` | property |
| [`EnsemblePageClassifier.votes_required`](../../collector/classification/ensemble.py#L91) | `votes_required(self) -> int` | property |
| [`EnsemblePageClassifier.minimum_successful_votes`](../../collector/classification/ensemble.py#L95) | `minimum_successful_votes(self) -> int` | property |
| [`EnsemblePageClassifier.classify`](../../collector/classification/ensemble.py#L99) | `classify(self, page: PageSnapshot, distributions: list[DistributionCandidate]) -> PageClassification` | function / method |
| [`EnsembleRepositoryRelevanceClassifier.__init__`](../../collector/classification/ensemble.py#L177) | `__init__(self, voters: list[tuple[str, RepositoryResultClassifier]] \| tuple[tuple[str, RepositoryResultClassifier], ...], votes_required: int=2, minimum_successful_votes: int \| None=None) -> None` | function / method |
| [`EnsembleRepositoryRelevanceClassifier.voter_ids`](../../collector/classification/ensemble.py#L206) | `voter_ids(self) -> tuple[str, ...]` | property |
| [`EnsembleRepositoryRelevanceClassifier.votes_required`](../../collector/classification/ensemble.py#L210) | `votes_required(self) -> int` | property |
| [`EnsembleRepositoryRelevanceClassifier.minimum_successful_votes`](../../collector/classification/ensemble.py#L214) | `minimum_successful_votes(self) -> int` | property |
| [`EnsembleRepositoryRelevanceClassifier.classify`](../../collector/classification/ensemble.py#L218) | `classify(self, page: PageSnapshot) -> RepositoryClassification` | function / method |
| [`_page_vote`](../../collector/classification/ensemble.py#L307) | `_page_vote(voter_id: str, classification: PageClassification) -> PageClassificationVote` | function / method |
| [`_repository_vote`](../../collector/classification/ensemble.py#L318) | `_repository_vote(voter_id: str, classification: RepositoryClassification) -> RepositoryClassificationVote` | function / method |
| [`_minimum_votes_error`](../../collector/classification/ensemble.py#L330) | `_minimum_votes_error(minimum_successful_votes: int, successful_votes: int, failures: list[dict[str, str]]) -> str` | function / method |
| [`_ensemble_summary`](../../collector/classification/ensemble.py#L351) | `_ensemble_summary(*, voters: list[dict[str, object]], failures: list[dict[str, object]], votes_required: int, minimum_successful_votes: int, accepted_votes: int, decision: str, decision_reason: str, decision_voter_ids: list[str]) -> dict[str, object]` | function / method |
| [`_vote_summary`](../../collector/classification/ensemble.py#L376) | `_vote_summary(vote: PageClassificationVote) -> dict[str, object]` | function / method |
| [`_repository_vote_summary`](../../collector/classification/ensemble.py#L386) | `_repository_vote_summary(vote: RepositoryClassificationVote) -> dict[str, object]` | function / method |
| [`_decision_votes`](../../collector/classification/ensemble.py#L398) | `_decision_votes(votes: list[PageClassificationVote], accepted: bool) -> list[PageClassificationVote]` | function / method |
| [`_decision_reason`](../../collector/classification/ensemble.py#L416) | `_decision_reason(*, accepted: bool, votes: list[PageClassificationVote], votes_required: int) -> str` | function / method |
| [`_repository_decision_votes`](../../collector/classification/ensemble.py#L437) | `_repository_decision_votes(votes: list[RepositoryClassificationVote], accepted: bool) -> list[RepositoryClassificationVote]` | function / method |
| [`_repository_decision_reason`](../../collector/classification/ensemble.py#L455) | `_repository_decision_reason(*, accepted: bool, votes: list[RepositoryClassificationVote], votes_required: int) -> str` | function / method |
| [`_majority_relevance_label`](../../collector/classification/ensemble.py#L476) | `_majority_relevance_label(votes: Iterable[RepositoryClassificationVote]) -> RepositoryRelevanceLabel` | function / method |
| [`_relevance_reason`](../../collector/classification/ensemble.py#L501) | `_relevance_reason(votes: Iterable[RepositoryClassificationVote], relevance_label: RepositoryRelevanceLabel) -> str` | function / method |
| [`_combined_missing_information`](../../collector/classification/ensemble.py#L518) | `_combined_missing_information(votes: Iterable[RepositoryClassificationVote], relevance_label: RepositoryRelevanceLabel) -> list[str]` | function / method |

<a id="collector-classification-factory-py"></a>

## collector/classification/factory.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`validate_default_classifier_configuration`](../../collector/classification/factory.py#L50) | `validate_default_classifier_configuration() -> None` | function / method |
| [`_voters`](../../collector/classification/factory.py#L59) | `_voters(provider_builder, classifier_type, validate, vote_store)` | function / method |
| [`build_default_page_classifier`](../../collector/classification/factory.py#L95) | `build_default_page_classifier(*, vote_store: VoteStore \| None=None) -> PageClassifier` | function / method |
| [`build_default_repository_result_classifier`](../../collector/classification/factory.py#L109) | `build_default_repository_result_classifier(*, vote_store: VoteStore \| None=None) -> RepositoryResultClassifier` | function / method |

<a id="collector-classification-llm_client-py"></a>

## collector/classification/llm_client.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_RejectLLMRedirects.redirect_request`](../../collector/classification/llm_client.py#L35) | `redirect_request(self, req, fp, code, msg, headers, newurl)` | function / method |
| [`extract_chat_completions_message_text`](../../collector/classification/llm_client.py#L39) | `extract_chat_completions_message_text(response_payload: object) -> str` | function / method |
| [`LLMClassificationClient.classify_payload`](../../collector/classification/llm_client.py#L66) | `classify_payload(self, payload: dict[str, object]) -> dict[str, object]` | function / method |
| [`HTTPJSONLLMClient.__init__`](../../collector/classification/llm_client.py#L88) | `__init__(self, provider: LLMProviderConfig, api_key: str \| None=None, model: str \| None=None, timeout_seconds: float=20.0, request: Callable[..., object] \| None=None) -> None` | function / method |
| [`HTTPJSONLLMClient.classify_payload`](../../collector/classification/llm_client.py#L104) | `classify_payload(self, payload: dict[str, object]) -> dict[str, object]` | function / method |
| [`HTTPJSONLLMClient.prepare_request`](../../collector/classification/llm_client.py#L107) | `prepare_request(self, payload: dict[str, object]) -> dict[str, object]` | function / method |
| [`HTTPJSONLLMClient.request_configuration`](../../collector/classification/llm_client.py#L111) | `request_configuration(self) -> dict[str, object]` | function / method |
| [`HTTPJSONLLMClient.classify_request`](../../collector/classification/llm_client.py#L114) | `classify_request(self, request_body: dict[str, object]) -> dict[str, object]` | function / method |
| [`HTTPJSONLLMClient._classify_request`](../../collector/classification/llm_client.py#L125) | `_classify_request(self, request_body, measurement)` | function / method |
| [`HTTPJSONLLMClient._request_body`](../../collector/classification/llm_client.py#L225) | `_request_body(self, payload: dict[str, object]) -> dict[str, object]` | function / method |

<a id="collector-classification-page-py"></a>

## collector/classification/page.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`PageClassificationError.__init__`](../../collector/classification/page.py#L13) | `__init__(self, message: str, *, code='processing_failed', recovery='manual', retry_at=None, diagnostics=None)` | function / method |
| [`PageClassifier.classify`](../../collector/classification/page.py#L61) | `classify(self, page: PageSnapshot, distributions: list[DistributionCandidate]) -> PageClassification` | function / method |

<a id="collector-classification-page_llm_classifier-py"></a>

## collector/classification/page_llm_classifier.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`LLMPageClassifier.__init__`](../../collector/classification/page_llm_classifier.py#L31) | `__init__(self, client: LLMClassificationClient) -> None` | function / method |
| [`LLMPageClassifier.classify`](../../collector/classification/page_llm_classifier.py#L37) | `classify(self, page: PageSnapshot, distributions: list[DistributionCandidate]) -> PageClassification` | function / method |
| [`_build_llm_payload`](../../collector/classification/page_llm_classifier.py#L56) | `_build_llm_payload(page: PageSnapshot, distributions: list[DistributionCandidate]) -> dict[str, object]` | function / method |
| [`_bounded_metadata_value`](../../collector/classification/page_llm_classifier.py#L96) | `_bounded_metadata_value(key: str, value: str) -> str` | function / method |
| [`_parse_page_classification`](../../collector/classification/page_llm_classifier.py#L109) | `_parse_page_classification(raw: dict[str, object]) -> PageClassification` | function / method |
| [`_required_bool`](../../collector/classification/page_llm_classifier.py#L126) | `_required_bool(raw: dict[str, object], field_name: str) -> bool` | function / method |
| [`_required_signal_object`](../../collector/classification/page_llm_classifier.py#L135) | `_required_signal_object(raw: dict[str, object], field_name: str) -> dict[str, object]` | function / method |

<a id="collector-classification-prompts-py"></a>

## collector/classification/prompts.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_build_epfl_rcp_chat_completions_request_body`](../../collector/classification/prompts.py#L8) | `_build_epfl_rcp_chat_completions_request_body(payload: dict[str, object], model: str) -> dict[str, object]` | function / method |
| [`_build_epfl_rcp_repository_relevance_request_body`](../../collector/classification/prompts.py#L20) | `_build_epfl_rcp_repository_relevance_request_body(payload: dict[str, object], model: str) -> dict[str, object]` | function / method |
| [`_build_chat_completions_request_body`](../../collector/classification/prompts.py#L32) | `_build_chat_completions_request_body(payload: dict[str, object], model: str, *, system_prompt: str, schema: dict[str, object]) -> dict[str, object]` | function / method |
| [`_system_prompt`](../../collector/classification/prompts.py#L59) | `_system_prompt() -> str` | function / method |
| [`_repository_relevance_system_prompt`](../../collector/classification/prompts.py#L79) | `_repository_relevance_system_prompt() -> str` | function / method |
| [`_classification_schema`](../../collector/classification/prompts.py#L203) | `_classification_schema() -> dict[str, object]` | function / method |
| [`_repository_relevance_schema`](../../collector/classification/prompts.py#L228) | `_repository_relevance_schema() -> dict[str, object]` | function / method |

<a id="collector-classification-providers-epfl_rcp-py"></a>

## collector/classification/providers/epfl_rcp.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`epfl_rcp_chat_completions_provider_config`](../../collector/classification/providers/epfl_rcp.py#L20) | `epfl_rcp_chat_completions_provider_config(*, name: str, model_env_var: str, default_model: str, api_key_env_var: str) -> LLMProviderConfig` | function / method |
| [`epfl_rcp_repository_relevance_provider_config`](../../collector/classification/providers/epfl_rcp.py#L39) | `epfl_rcp_repository_relevance_provider_config(*, name: str, model_env_var: str, default_model: str, api_key_env_var: str) -> LLMProviderConfig` | function / method |

<a id="collector-classification-repository-py"></a>

## collector/classification/repository.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RepositoryClassification.__post_init__`](../../collector/classification/repository.py#L65) | `__post_init__(self) -> None` | function / method |
| [`RepositoryClassificationVote.__post_init__`](../../collector/classification/repository.py#L99) | `__post_init__(self) -> None` | function / method |
| [`RepositoryResultClassifier.classify`](../../collector/classification/repository.py#L121) | `classify(self, page: PageSnapshot) -> RepositoryClassification` | function / method |
| [`_validate_relevance_label`](../../collector/classification/repository.py#L125) | `_validate_relevance_label(value: object) -> None` | function / method |
| [`_normalized_missing_information`](../../collector/classification/repository.py#L130) | `_normalized_missing_information(relevance_label: RepositoryRelevanceLabel, values: list[str]) -> list[str]` | function / method |

<a id="collector-classification-repository_llm_classifier-py"></a>

## collector/classification/repository_llm_classifier.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`LLMRepositoryRelevanceClassifier.__init__`](../../collector/classification/repository_llm_classifier.py#L38) | `__init__(self, client: LLMClassificationClient) -> None` | function / method |
| [`LLMRepositoryRelevanceClassifier.classify`](../../collector/classification/repository_llm_classifier.py#L44) | `classify(self, page: PageSnapshot) -> RepositoryClassification` | function / method |
| [`_build_repository_relevance_payload`](../../collector/classification/repository_llm_classifier.py#L59) | `_build_repository_relevance_payload(page: PageSnapshot) -> dict[str, object]` | function / method |
| [`_repository_metadata_value`](../../collector/classification/repository_llm_classifier.py#L84) | `_repository_metadata_value(key: str, value: str) -> str` | function / method |
| [`_parse_repository_relevance_classification`](../../collector/classification/repository_llm_classifier.py#L96) | `_parse_repository_relevance_classification(raw: dict[str, object]) -> RepositoryClassification` | function / method |
| [`_required_relevance_label`](../../collector/classification/repository_llm_classifier.py#L119) | `_required_relevance_label(raw: dict[str, object], field_name: str) -> RepositoryRelevanceLabel` | function / method |
| [`_required_non_empty_string`](../../collector/classification/repository_llm_classifier.py#L132) | `_required_non_empty_string(raw: dict[str, object], field_name: str) -> str` | function / method |
| [`_required_string_list`](../../collector/classification/repository_llm_classifier.py#L147) | `_required_string_list(raw: dict[str, object], field_name: str) -> list[str]` | function / method |

<a id="collector-classification-voting-py"></a>

## collector/classification/voting.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`run_voters`](../../collector/classification/voting.py#L31) | `run_voters(voters: Sequence[tuple[str, ClassifierT]], *, classify: Callable[[ClassifierT], ClassificationT], make_vote: Callable[[str, ClassificationT], VoteT], handled_errors: tuple[type[Exception], ...]) -> list[VoteOutcome[VoteT]]` | function / method |
| [`run_voters.<local>.invoke`](../../collector/classification/voting.py#L46) | `invoke(voter: tuple[str, ClassifierT]) -> VoteOutcome[VoteT]` | function / method |

<a id="collector-collection-browser-py"></a>

## collector/collection/browser.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`BrowserSession.__init__`](../../collector/collection/browser.py#L38) | `__init__(self, endpoint, token, config, *, registry=None)` | function / method |
| [`BrowserSession.request`](../../collector/collection/browser.py#L43) | `request(self, action, payload, *, closing=False)` | function / method |
| [`BrowserSession._request`](../../collector/collection/browser.py#L48) | `_request(self, action, payload, *, closing=False)` | function / method |
| [`BrowserSession.render`](../../collector/collection/browser.py#L123) | `render(self, url, *, metadata_url=None)` | function / method |
| [`BrowserSession.probe`](../../collector/collection/browser.py#L170) | `probe(self, url, method, timeout, max_bytes, headers=None)` | function / method |
| [`BrowserSession.validate`](../../collector/collection/browser.py#L198) | `validate(self, distribution)` | function / method |
| [`BrowserSession.close`](../../collector/collection/browser.py#L206) | `close(self)` | function / method |
| [`configured_browser`](../../collector/collection/browser.py#L215) | `configured_browser(config, source_url=None)` | contextmanager |

<a id="collector-collection-compatibility-py"></a>

## collector/collection/compatibility.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`to_strategy_result`](../../collector/collection/compatibility.py#L10) | `to_strategy_result(record: NormalizedRecord, method: str) -> StrategyResult` | function / method |

<a id="collector-collection-connectors-__init__-py"></a>

## collector/collection/connectors/__init__.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RecordConnector.supports`](../../collector/collection/connectors/__init__.py#L20) | `supports(self, url: str) -> bool` | function / method |
| [`RecordConnector.api_url`](../../collector/collection/connectors/__init__.py#L24) | `api_url(self, url: str) -> str \| None` | function / method |
| [`RecordConnector.reference_identity`](../../collector/collection/connectors/__init__.py#L28) | `reference_identity(self, url: str) -> RecordIdentity` | function / method |
| [`RecordConnector.normalize`](../../collector/collection/connectors/__init__.py#L32) | `normalize(self, url: str, payload: dict \| list) -> NormalizedRecord` | function / method |
| [`RecordConnector.scope_resources`](../../collector/collection/connectors/__init__.py#L36) | `scope_resources(self, url: str, resources: list[DistributionCandidate], known_record: NormalizedRecord \| None=None) -> list[DistributionCandidate]` | function / method |

<a id="collector-collection-connectors-dataverse-py"></a>

## collector/collection/connectors/dataverse.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`DataverseConnector.__init__`](../../collector/collection/connectors/dataverse.py#L18) | `__init__(self, hosts: tuple[str, ...])` | function / method |
| [`DataverseConnector.supports`](../../collector/collection/connectors/dataverse.py#L21) | `supports(self, url: str) -> bool` | function / method |
| [`DataverseConnector.api_url`](../../collector/collection/connectors/dataverse.py#L33) | `api_url(self, url: str) -> str \| None` | function / method |
| [`DataverseConnector.normalize`](../../collector/collection/connectors/dataverse.py#L67) | `normalize(self, url: str, payload: dict \| list) -> NormalizedRecord` | function / method |
| [`DataverseConnector.reference_identity`](../../collector/collection/connectors/dataverse.py#L172) | `reference_identity(self, url: str) -> RecordIdentity` | function / method |
| [`DataverseConnector.scope_resources`](../../collector/collection/connectors/dataverse.py#L189) | `scope_resources(self, url: str, resources: list[DistributionCandidate], known_record: NormalizedRecord \| None=None) -> list[DistributionCandidate]` | function / method |

<a id="collector-collection-connectors-dryad-py"></a>

## collector/collection/connectors/dryad.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`DryadConnector.supports`](../../collector/collection/connectors/dryad.py#L26) | `supports(self, url)` | function / method |
| [`DryadConnector._doi`](../../collector/collection/connectors/dryad.py#L29) | `_doi(self, url)` | function / method |
| [`DryadConnector.api_url`](../../collector/collection/connectors/dryad.py#L40) | `api_url(self, url)` | function / method |
| [`DryadConnector.reference_identity`](../../collector/collection/connectors/dryad.py#L44) | `reference_identity(self, url)` | function / method |
| [`DryadConnector.fetch_metadata`](../../collector/collection/connectors/dryad.py#L50) | `fetch_metadata(self, url, fetch_json)` | function / method |
| [`DryadConnector.normalize`](../../collector/collection/connectors/dryad.py#L69) | `normalize(self, url, payload)` | function / method |
| [`DryadConnector.scope_resources`](../../collector/collection/connectors/dryad.py#L139) | `scope_resources(self, url, resources, known_record=None)` | function / method |

<a id="collector-collection-connectors-dspace-py"></a>

## collector/collection/connectors/dspace.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`uuid`](../../collector/collection/connectors/dspace.py#L24) | `uuid(value)` | function / method |
| [`metadata_values`](../../collector/collection/connectors/dspace.py#L31) | `metadata_values(metadata, key)` | function / method |
| [`DSpaceConnector.__init__`](../../collector/collection/connectors/dspace.py#L44) | `__init__(self, api_bases=())` | function / method |
| [`DSpaceConnector.supports`](../../collector/collection/connectors/dspace.py#L59) | `supports(self, url)` | function / method |
| [`DSpaceConnector.api_url`](../../collector/collection/connectors/dspace.py#L62) | `api_url(self, url)` | function / method |
| [`DSpaceConnector.reference_identity`](../../collector/collection/connectors/dspace.py#L76) | `reference_identity(self, url)` | function / method |
| [`DSpaceConnector._validate_item`](../../collector/collection/connectors/dspace.py#L87) | `_validate_item(self, url, item)` | function / method |
| [`DSpaceConnector.fetch_metadata`](../../collector/collection/connectors/dspace.py#L98) | `fetch_metadata(self, url, fetch_json)` | function / method |
| [`DSpaceConnector.normalize`](../../collector/collection/connectors/dspace.py#L126) | `normalize(self, url, payload)` | function / method |
| [`DSpaceConnector.scope_resources`](../../collector/collection/connectors/dspace.py#L183) | `scope_resources(self, url, resources, known_record=None)` | function / method |

<a id="collector-collection-connectors-figshare-py"></a>

## collector/collection/connectors/figshare.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`FigshareConnector.__init__`](../../collector/collection/connectors/figshare.py#L26) | `__init__(self, hosts: tuple[str, ...]=('figshare.com', 'springernature.figshare.com'))` | function / method |
| [`FigshareConnector.supports`](../../collector/collection/connectors/figshare.py#L29) | `supports(self, url: str) -> bool` | function / method |
| [`FigshareConnector.api_url`](../../collector/collection/connectors/figshare.py#L32) | `api_url(self, url: str) -> str \| None` | function / method |
| [`FigshareConnector.reference_identity`](../../collector/collection/connectors/figshare.py#L42) | `reference_identity(self, url: str) -> RecordIdentity` | function / method |
| [`FigshareConnector.normalize`](../../collector/collection/connectors/figshare.py#L51) | `normalize(self, url: str, payload: dict \| list) -> NormalizedRecord` | function / method |
| [`FigshareConnector.scope_resources`](../../collector/collection/connectors/figshare.py#L101) | `scope_resources(self, url: str, resources: list[DistributionCandidate], known_record: NormalizedRecord \| None=None) -> list[DistributionCandidate]` | function / method |

<a id="collector-collection-connectors-inveniordm-py"></a>

## collector/collection/connectors/inveniordm.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`InvenioRDMConnector.__init__`](../../collector/collection/connectors/inveniordm.py#L26) | `__init__(self, hosts=())` | function / method |
| [`InvenioRDMConnector.supports`](../../collector/collection/connectors/inveniordm.py#L29) | `supports(self, url)` | function / method |
| [`InvenioRDMConnector.api_url`](../../collector/collection/connectors/inveniordm.py#L32) | `api_url(self, url)` | function / method |
| [`InvenioRDMConnector.reference_identity`](../../collector/collection/connectors/inveniordm.py#L44) | `reference_identity(self, url)` | function / method |
| [`InvenioRDMConnector.fetch_metadata`](../../collector/collection/connectors/inveniordm.py#L52) | `fetch_metadata(self, url, fetch_json)` | function / method |
| [`InvenioRDMConnector._validate_record`](../../collector/collection/connectors/inveniordm.py#L68) | `_validate_record(self, url, record)` | function / method |
| [`InvenioRDMConnector.normalize`](../../collector/collection/connectors/inveniordm.py#L78) | `normalize(self, url, payload)` | function / method |
| [`InvenioRDMConnector.scope_resources`](../../collector/collection/connectors/inveniordm.py#L154) | `scope_resources(self, url, resources, known_record=None)` | function / method |

<a id="collector-collection-connectors-metadata-py"></a>

## collector/collection/connectors/metadata.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`file_resource`](../../collector/collection/connectors/metadata.py#L16) | `file_resource(name, url, *, key, mime='', size=None, restricted=False)` | function / method |
| [`known_resources`](../../collector/collection/connectors/metadata.py#L31) | `known_resources(resources, known_record)` | function / method |
| [`api_link`](../../collector/collection/connectors/metadata.py#L36) | `api_link(api_root: str, value: str) -> str` | function / method |
| [`hal_link`](../../collector/collection/connectors/metadata.py#L56) | `hal_link(payload: dict, key: str) -> str` | function / method |
| [`MetadataReader.__init__`](../../collector/collection/connectors/metadata.py#L64) | `__init__(self, api_root, fetch_json)` | function / method |
| [`MetadataReader.read`](../../collector/collection/connectors/metadata.py#L69) | `read(self, url)` | function / method |
| [`MetadataReader.response`](../../collector/collection/connectors/metadata.py#L89) | `response(self, payload)` | function / method |
| [`MetadataReader.listing`](../../collector/collection/connectors/metadata.py#L96) | `listing(self, url, key)` | function / method |

<a id="collector-collection-connectors-shared-py"></a>

## collector/collection/connectors/shared.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`repository_origin`](../../collector/collection/connectors/shared.py#L8) | `repository_origin(url: str, hosts: tuple[str, ...]) -> str \| None` | function / method |
| [`text`](../../collector/collection/connectors/shared.py#L24) | `text(value: object) -> str` | function / method |
| [`positive_id`](../../collector/collection/connectors/shared.py#L28) | `positive_id(value: object) -> str` | function / method |

<a id="collector-collection-connectors-zenodo-py"></a>

## collector/collection/connectors/zenodo.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`reference_match`](../../collector/collection/connectors/zenodo.py#L20) | `reference_match(url: str)` | function / method |
| [`ZenodoConnector.__init__`](../../collector/collection/connectors/zenodo.py#L29) | `__init__(self, hosts: tuple[str, ...]=('zenodo.org',))` | function / method |
| [`ZenodoConnector.supports`](../../collector/collection/connectors/zenodo.py#L32) | `supports(self, url: str) -> bool` | function / method |
| [`ZenodoConnector.api_url`](../../collector/collection/connectors/zenodo.py#L35) | `api_url(self, url: str) -> str \| None` | function / method |
| [`ZenodoConnector.normalize`](../../collector/collection/connectors/zenodo.py#L44) | `normalize(self, url: str, payload: dict \| list) -> NormalizedRecord` | function / method |
| [`ZenodoConnector.scope_resources`](../../collector/collection/connectors/zenodo.py#L120) | `scope_resources(self, url: str, resources: list[DistributionCandidate], known_record: NormalizedRecord \| None=None) -> list[DistributionCandidate]` | function / method |
| [`ZenodoConnector.reference_identity`](../../collector/collection/connectors/zenodo.py#L147) | `reference_identity(self, url: str) -> RecordIdentity` | function / method |

<a id="collector-collection-contracts-py"></a>

## collector/collection/contracts.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`public_url`](../../collector/collection/contracts.py#L14) | `public_url(value: str) -> str` | function / method |

<a id="collector-collection-failures-py"></a>

## collector/collection/failures.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`CollectionStepError.__init__`](../../collector/collection/failures.py#L11) | `__init__(self, code: str, phase: str, *, http_status: int \| None=None, final_url: str='', service_http_status: int \| None=None)` | function / method |

<a id="collector-collection-http-py"></a>

## collector/collection/http.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`fetch_record_json`](../../collector/collection/http.py#L35) | `fetch_record_json(url: str, *, timeout: float=DEFAULT_CONFIG.record_request_timeout_seconds, max_bytes: int=5000000, user_agent: str=DEFAULT_CONFIG.user_agent, max_attempts: int=DEFAULT_CONFIG.record_max_attempts, max_retry_wait: float=DEFAULT_CONFIG.record_retry_max_wait_seconds) -> JsonResponse` | function / method |
| [`_transient_network_error`](../../collector/collection/http.py#L94) | `_transient_network_error(exc: Exception \| None) -> bool` | function / method |
| [`_fetch_record_json_once`](../../collector/collection/http.py#L108) | `_fetch_record_json_once(url, *, timeout, max_bytes, user_agent) -> JsonResponse` | function / method |

<a id="collector-collection-orchestrator-py"></a>

## collector/collection/orchestrator.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`now`](../../collector/collection/orchestrator.py#L27) | `now()` | function / method |
| [`collect_record`](../../collector/collection/orchestrator.py#L31) | `collect_record(url: str, config: CollectorConfig, *, fetch_html=None, fetch_json=None, validate=None, classifier=None, browser=None, observe=None, registry: ConnectorRegistry \| None=None) -> CollectionResult` | function / method |
| [`collect_record.<local>.related_json`](../../collector/collection/orchestrator.py#L104) | `related_json(metadata_url, *, evidence=evidence, request_count=request_count)` | function / method |
| [`collect_record.<local>.record_check`](../../collector/collection/orchestrator.py#L220) | `record_check(resource, validation, *, attempt=attempt)` | function / method |

<a id="collector-collection-pipeline-py"></a>

## collector/collection/pipeline.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`analyze_html_page`](../../collector/collection/pipeline.py#L24) | `analyze_html_page(url: str, html: str, config: CollectorConfig=DEFAULT_CONFIG, classifier: PageClassifier \| None=None, *, discovered_page: DiscoveredPage \| None=None, distribution_candidates: list[DistributionCandidate] \| None=None, record_url: str \| None=None, record_identity: dict[str, str] \| None=None, page_snapshot: PageSnapshot \| None=None) -> CollectedDataset \| None` | function / method |
| [`analyze_discovered_page`](../../collector/collection/pipeline.py#L104) | `analyze_discovered_page(discovered_page: DiscoveredPage, config: CollectorConfig=DEFAULT_CONFIG, classifier: PageClassifier \| None=None) -> CollectedDataset \| None` | function / method |
| [`_classifier_or_default`](../../collector/collection/pipeline.py#L178) | `_classifier_or_default(classifier: PageClassifier \| None) -> PageClassifier` | function / method |
| [`_usable_distribution`](../../collector/collection/pipeline.py#L183) | `_usable_distribution(distribution: DistributionCandidate) -> bool` | function / method |
| [`_merge_discovery_metadata`](../../collector/collection/pipeline.py#L193) | `_merge_discovery_metadata(page: PageSnapshot, discovered: DiscoveredPage) -> PageSnapshot` | function / method |
| [`eligible_resources`](../../collector/collection/pipeline.py#L217) | `eligible_resources(resolved: StrategyResult, *, expected_identity: dict[str, str] \| None=None) -> list[DistributionCandidate]` | function / method |
| [`classify_resolution`](../../collector/collection/pipeline.py#L230) | `classify_resolution(resolved: StrategyResult, resources: list[DistributionCandidate], config: CollectorConfig, classifier: PageClassifier \| None, *, record_url: str \| None=None, known_record: NormalizedRecord \| None=None, record_identity: dict[str, str] \| None=None) -> CollectedDataset \| None` | function / method |

<a id="collector-collection-records-py"></a>

## collector/collection/records.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RecordIdentity.to_dict`](../../collector/collection/records.py#L20) | `to_dict(self) -> dict[str, str]` | function / method |

<a id="collector-collection-registry-py"></a>

## collector/collection/registry.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ConnectorRegistry.__init__`](../../collector/collection/registry.py#L25) | `__init__(self, connectors: Iterable[RecordConnector])` | function / method |
| [`ConnectorRegistry.select`](../../collector/collection/registry.py#L31) | `select(self, url: str) -> ConnectorSelection \| None` | function / method |
| [`default_registry`](../../collector/collection/registry.py#L38) | `default_registry(config: CollectorConfig) -> ConnectorRegistry` | function / method |

<a id="collector-collection-resources-py"></a>

## collector/collection/resources.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`retain_validated_resources`](../../collector/collection/resources.py#L29) | `retain_validated_resources(resources: list[DistributionCandidate], config: CollectorConfig, validate: Callable[[DistributionCandidate], ValidationResult], *, state: ResourceCheckState \| None=None, context: str='http', on_check: Callable[[DistributionCandidate, ValidationResult], None] \| None=None) -> ResourceSelection` | function / method |

<a id="collector-collection-service-py"></a>

## collector/collection/service.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`collect_source_with_report`](../../collector/collection/service.py#L44) | `collect_source_with_report(source_url: str, config: CollectorConfig=DEFAULT_CONFIG, discover: DiscoverFunction \| None=None, fetch_html: FetchHTMLFunction \| None=None, validate: ValidateDistributionFunction \| None=None, classifier: PageClassifier \| None=None, *, browser=None) -> CollectionResult` | function / method |
| [`_collect_source_within_budget`](../../collector/collection/service.py#L77) | `_collect_source_within_budget(source_url, config, discover, fetch_html, validate, classifier, browser)` | function / method |
| [`collect_repository_candidate_with_report`](../../collector/collection/service.py#L180) | `collect_repository_candidate_with_report(candidate_url: str, config: CollectorConfig=DEFAULT_CONFIG, fetch_html: FetchHTMLFunction \| None=None, validate: ValidateDistributionFunction \| None=None, classifier: PageClassifier \| None=None, *, fetch_json=None, browser=None, observe=None, registry=None) -> CollectionResult` | function / method |
| [`_collect_discovered_page_with_report`](../../collector/collection/service.py#L211) | `_collect_discovered_page_with_report(discovered_page: DiscoveredPage, config: CollectorConfig, fetch_html: FetchHTMLFunction, validate: ValidateDistributionFunction, classifier: PageClassifier \| None=None, *, validation_failures: list[ValidationResult] \| None=None, browser=None, diagnostics: list[Diagnostic] \| None=None) -> tuple[CollectedDataset \| None, int]` | function / method |
| [`_collect_discovered_page_with_report.<local>.failed_html`](../../collector/collection/service.py#L254) | `failed_html(_, *, error=exception)` | function / method |
| [`_with_valid_distributions_and_report`](../../collector/collection/service.py#L288) | `_with_valid_distributions_and_report(dataset: CollectedDataset, config: CollectorConfig, validate: ValidateDistributionFunction, *, failures: list[ValidationResult] \| None=None) -> tuple[CollectedDataset \| None, int]` | function / method |

<a id="collector-collection-strategies-dataverse-py"></a>

## collector/collection/strategies/dataverse.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`record_api_url`](../../collector/collection/strategies/dataverse.py#L12) | `record_api_url(url: str, hosts: tuple[str, ...]) -> str \| None` | function / method |
| [`resolve_metadata`](../../collector/collection/strategies/dataverse.py#L16) | `resolve_metadata(url: str, payload: dict \| list) -> StrategyResult` | function / method |

<a id="collector-config-py"></a>

## collector/config.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`CollectorConfig.__post_init__`](../../collector/config.py#L33) | `__post_init__(self)` | function / method |
| [`validate_collection_budget_seconds`](../../collector/config.py#L45) | `validate_collection_budget_seconds(value: float) -> float` | function / method |
| [`configured_collection_budget_seconds`](../../collector/config.py#L51) | `configured_collection_budget_seconds() -> float` | function / method |
| [`configured_record_transport`](../../collector/config.py#L60) | `configured_record_transport() -> dict[str, float \| int]` | function / method |
| [`configured_repository_connectors`](../../collector/config.py#L74) | `configured_repository_connectors() -> dict` | function / method |

<a id="collector-diagnostics-py"></a>

## collector/diagnostics.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`Diagnostic.message`](../../collector/diagnostics.py#L77) | `message(self) -> str` | property |
| [`Diagnostic.to_dict`](../../collector/diagnostics.py#L81) | `to_dict(self) -> dict` | function / method |
| [`PipelineFailure.__init__`](../../collector/diagnostics.py#L86) | `__init__(self, message: str, *, diagnostics: list[Diagnostic])` | function / method |
| [`PersistenceFailure.__init__`](../../collector/diagnostics.py#L94) | `__init__(self, message: str, *, stage: Stage='classification') -> None` | function / method |
| [`exception_diagnostics`](../../collector/diagnostics.py#L98) | `exception_diagnostics(exception: Exception, stage: Stage) -> list[Diagnostic]` | function / method |
| [`public_diagnostics`](../../collector/diagnostics.py#L104) | `public_diagnostics(values: list[dict]) -> list[dict]` | function / method |
| [`voter_diagnostics`](../../collector/diagnostics.py#L117) | `voter_diagnostics(exception: Exception, voter_id: str, attempt=None) -> list[Diagnostic]` | function / method |
| [`retry_after`](../../collector/diagnostics.py#L124) | `retry_after(value: str \| None, *, now: datetime \| None=None) -> str \| None` | function / method |

<a id="collector-discovery-adapters-__init__-py"></a>

## collector/discovery/adapters/__init__.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`default_adapters`](../../collector/discovery/adapters/__init__.py#L19) | `default_adapters(config: CollectorConfig=DEFAULT_CONFIG) -> tuple[DiscoveryAdapter, ...]` | function / method |

<a id="collector-discovery-adapters-ckan-py"></a>

## collector/discovery/adapters/ckan.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`CKANAdapter.__init__`](../../collector/discovery/adapters/ckan.py#L34) | `__init__(self, fetch_json: JsonFetcher \| None=None, rows: int=5) -> None` | function / method |
| [`CKANAdapter.detect`](../../collector/discovery/adapters/ckan.py#L42) | `detect(self, source_url: str) -> bool` | function / method |
| [`CKANAdapter.discover`](../../collector/discovery/adapters/ckan.py#L50) | `discover(self, source_url: str) -> list[DiscoveredPage]` | function / method |
| [`_ckan_action_url`](../../collector/discovery/adapters/ckan.py#L110) | `_ckan_action_url(source_url: str, action: str, params: dict[str, str] \| None=None) -> str` | function / method |
| [`_ckan_site_root`](../../collector/discovery/adapters/ckan.py#L123) | `_ckan_site_root(source_url: str) -> str` | function / method |
| [`_ckan_search_params`](../../collector/discovery/adapters/ckan.py#L128) | `_ckan_search_params(source_url: str, rows: int) -> dict[str, str]` | function / method |
| [`_dataset_page_url`](../../collector/discovery/adapters/ckan.py#L140) | `_dataset_page_url(source_url: str, package: dict[object, object]) -> str` | function / method |
| [`_distribution_candidates`](../../collector/discovery/adapters/ckan.py#L152) | `_distribution_candidates(source_url: str, package: dict[object, object]) -> list[DistributionCandidate]` | function / method |
| [`_publisher`](../../collector/discovery/adapters/ckan.py#L194) | `_publisher(package: dict[object, object]) -> str` | function / method |
| [`_size_from_ckan_package`](../../collector/discovery/adapters/ckan.py#L202) | `_size_from_ckan_package(package: dict[object, object]) -> str` | function / method |

<a id="collector-discovery-adapters-data_json-py"></a>

## collector/discovery/adapters/data_json.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`DataJsonAdapter.__init__`](../../collector/discovery/adapters/data_json.py#L42) | `__init__(self, fetch_json: JsonFetcher \| None=None, rows: int=5) -> None` | function / method |
| [`DataJsonAdapter.detect`](../../collector/discovery/adapters/data_json.py#L50) | `detect(self, source_url: str) -> bool` | function / method |
| [`DataJsonAdapter.discover`](../../collector/discovery/adapters/data_json.py#L58) | `discover(self, source_url: str) -> list[DiscoveredPage]` | function / method |
| [`_data_json_url`](../../collector/discovery/adapters/data_json.py#L114) | `_data_json_url(source_url: str) -> str` | function / method |
| [`_data_json_datasets`](../../collector/discovery/adapters/data_json.py#L122) | `_data_json_datasets(data: dict[str, object]) -> list[dict[object, object]]` | function / method |
| [`_data_json_dataset_url`](../../collector/discovery/adapters/data_json.py#L138) | `_data_json_dataset_url(data_json_url: str, dataset: dict[object, object]) -> str` | function / method |
| [`_data_json_distribution_candidates`](../../collector/discovery/adapters/data_json.py#L154) | `_data_json_distribution_candidates(data_json_url: str, dataset: dict[object, object]) -> list[DistributionCandidate]` | function / method |
| [`_data_json_format`](../../collector/discovery/adapters/data_json.py#L223) | `_data_json_format(resource_url: str, format_text: str, media_type: str, anchor: str, has_download_url: bool) -> tuple[str, str]` | function / method |
| [`_data_json_publisher`](../../collector/discovery/adapters/data_json.py#L242) | `_data_json_publisher(dataset: dict[object, object]) -> str` | function / method |
| [`_size_from_data_json_dataset`](../../collector/discovery/adapters/data_json.py#L250) | `_size_from_data_json_dataset(dataset: dict[object, object]) -> str` | function / method |
| [`_data_json_distribution_items`](../../collector/discovery/adapters/data_json.py#L271) | `_data_json_distribution_items(dataset: dict[object, object]) -> list[dict[object, object]]` | function / method |
| [`_modalities_from_data_json_dataset`](../../collector/discovery/adapters/data_json.py#L275) | `_modalities_from_data_json_dataset(dataset: dict[object, object], distributions: tuple[DistributionCandidate, ...]) -> tuple[str, ...]` | function / method |
| [`_data_json_dataset_matches_query`](../../collector/discovery/adapters/data_json.py#L287) | `_data_json_dataset_matches_query(dataset: dict[object, object], query: str) -> bool` | function / method |
| [`_source_query`](../../collector/discovery/adapters/data_json.py#L300) | `_source_query(source_url: str) -> str` | function / method |

<a id="collector-discovery-adapters-generic-py"></a>

## collector/discovery/adapters/generic.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`GenericWebsiteAdapter.__init__`](../../collector/discovery/adapters/generic.py#L15) | `__init__(self, fetch_text: TextFetcher \| None=None, max_sitemap_urls: int=50) -> None` | function / method |
| [`GenericWebsiteAdapter.detect`](../../collector/discovery/adapters/generic.py#L23) | `detect(self, source_url: str) -> bool` | function / method |
| [`GenericWebsiteAdapter.discover`](../../collector/discovery/adapters/generic.py#L26) | `discover(self, source_url: str) -> list[DiscoveredPage]` | function / method |

<a id="collector-discovery-adapters-shared-py"></a>

## collector/discovery/adapters/shared.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`JsonDocument.__init__`](../../collector/discovery/adapters/shared.py#L27) | `__init__(self, payload: dict[str, object], final_url: str) -> None` | function / method |
| [`document_url`](../../collector/discovery/adapters/shared.py#L32) | `document_url(payload: dict[str, object], requested_url: str) -> str` | function / method |
| [`DiscoveryAdapter.detect`](../../collector/discovery/adapters/shared.py#L128) | `detect(self, source_url: str) -> bool` | function / method |
| [`DiscoveryAdapter.discover`](../../collector/discovery/adapters/shared.py#L131) | `discover(self, source_url: str) -> list[DiscoveredPage]` | function / method |
| [`fetch_json_url`](../../collector/discovery/adapters/shared.py#L135) | `fetch_json_url(url: str, timeout: float=DEFAULT_CONFIG.request_timeout_seconds, max_bytes: int=5000000, user_agent: str=DEFAULT_CONFIG.user_agent, *, allow_list: bool=False) -> dict[str, object] \| list` | function / method |
| [`_geography_from_mapping`](../../collector/discovery/adapters/shared.py#L176) | `_geography_from_mapping(mapping: dict[object, object]) -> list[str]` | function / method |
| [`_publication_date_from_mapping`](../../collector/discovery/adapters/shared.py#L212) | `_publication_date_from_mapping(mapping: dict[object, object]) -> str` | function / method |
| [`_diseases_from_mapping`](../../collector/discovery/adapters/shared.py#L228) | `_diseases_from_mapping(*mappings: dict[object, object]) -> tuple[str, ...]` | function / method |
| [`_demographics_from_mapping`](../../collector/discovery/adapters/shared.py#L261) | `_demographics_from_mapping(*mappings: dict[object, object]) -> tuple[str, ...]` | function / method |
| [`_modalities_from_distributions`](../../collector/discovery/adapters/shared.py#L291) | `_modalities_from_distributions(distributions: tuple[DistributionCandidate, ...]) -> tuple[str, ...]` | function / method |
| [`_modalities_from_format`](../../collector/discovery/adapters/shared.py#L302) | `_modalities_from_format(value: str) -> list[str]` | function / method |
| [`_first_mapping_value`](../../collector/discovery/adapters/shared.py#L320) | `_first_mapping_value(mapping: dict[object, object], *keys: str) -> str` | function / method |
| [`_mapping_values`](../../collector/discovery/adapters/shared.py#L325) | `_mapping_values(mapping: dict[object, object], *keys: str) -> list[str]` | function / method |
| [`_mapping_dicts`](../../collector/discovery/adapters/shared.py#L341) | `_mapping_dicts(value: object) -> list[dict[object, object]]` | function / method |
| [`_value_text`](../../collector/discovery/adapters/shared.py#L349) | `_value_text(value: object) -> str` | function / method |
| [`_country_values`](../../collector/discovery/adapters/shared.py#L357) | `_country_values(value: object) -> list[str]` | function / method |
| [`_first_text`](../../collector/discovery/adapters/shared.py#L379) | `_first_text(mapping: dict[object, object], *keys: str) -> str` | function / method |
| [`_first_text_value`](../../collector/discovery/adapters/shared.py#L388) | `_first_text_value(value: object) -> str` | function / method |
| [`_text_values`](../../collector/discovery/adapters/shared.py#L402) | `_text_values(value: object) -> list[str]` | function / method |
| [`_dedupe`](../../collector/discovery/adapters/shared.py#L419) | `_dedupe(values: list[str]) -> list[str]` | function / method |
| [`_first_url`](../../collector/discovery/adapters/shared.py#L423) | `_first_url(*values: object) -> str` | function / method |
| [`_json_ld_type_matches`](../../collector/discovery/adapters/shared.py#L439) | `_json_ld_type_matches(value: object, expected_type: str) -> bool` | function / method |
| [`_site_root`](../../collector/discovery/adapters/shared.py#L455) | `_site_root(source_url: str) -> str` | function / method |
| [`_normalize_format`](../../collector/discovery/adapters/shared.py#L460) | `_normalize_format(value: str) -> str` | function / method |
| [`_text`](../../collector/discovery/adapters/shared.py#L471) | `_text(value: object) -> str` | function / method |

<a id="collector-discovery-adapters-socrata-py"></a>

## collector/discovery/adapters/socrata.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_socrata_pagination`](../../collector/discovery/adapters/socrata.py#L28) | `_socrata_pagination() -> dict[str, object]` | function / method |
| [`SocrataAdapter.__init__`](../../collector/discovery/adapters/socrata.py#L57) | `__init__(self, fetch_json: JsonFetcher \| None=None, rows: int=5) -> None` | function / method |
| [`SocrataAdapter.detect`](../../collector/discovery/adapters/socrata.py#L65) | `detect(self, source_url: str) -> bool` | function / method |
| [`SocrataAdapter.discover`](../../collector/discovery/adapters/socrata.py#L75) | `discover(self, source_url: str) -> list[DiscoveredPage]` | function / method |
| [`_socrata_catalog_url`](../../collector/discovery/adapters/socrata.py#L156) | `_socrata_catalog_url(source_url: str, rows: int, include_source_query: bool) -> str` | function / method |
| [`_socrata_domain`](../../collector/discovery/adapters/socrata.py#L176) | `_socrata_domain(source_url: str) -> str` | function / method |
| [`_socrata_results`](../../collector/discovery/adapters/socrata.py#L180) | `_socrata_results(data: dict[str, object], source_url: str) -> list[SocrataCatalogResult]` | function / method |
| [`_socrata_dataset_url`](../../collector/discovery/adapters/socrata.py#L220) | `_socrata_dataset_url(source_url: str, result: SocrataCatalogResult) -> str` | function / method |
| [`_socrata_distribution_candidates`](../../collector/discovery/adapters/socrata.py#L243) | `_socrata_distribution_candidates(source_url: str, socrata_id: str) -> list[DistributionCandidate]` | function / method |
| [`_socrata_site_root`](../../collector/discovery/adapters/socrata.py#L276) | `_socrata_site_root(source_url: str) -> str` | function / method |

<a id="collector-discovery-manager-py"></a>

## collector/discovery/manager.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`discover_source`](../../collector/discovery/manager.py#L9) | `discover_source(source_url: str, adapters: tuple[DiscoveryAdapter, ...] \| None=None, config: CollectorConfig=DEFAULT_CONFIG) -> list[DiscoveredPage]` | function / method |

<a id="collector-discovery-sitemap-py"></a>

## collector/discovery/sitemap.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`sitemap_urls_from_robots`](../../collector/discovery/sitemap.py#L83) | `sitemap_urls_from_robots(robots_text: str, source_url: str) -> list[str]` | function / method |
| [`default_sitemap_candidates`](../../collector/discovery/sitemap.py#L99) | `default_sitemap_candidates(source_url: str) -> list[str]` | function / method |
| [`discover_sitemap_entries`](../../collector/discovery/sitemap.py#L109) | `discover_sitemap_entries(source_url: str, fetch_text: TextFetcher \| None=None, max_sitemaps: int=MAX_SITEMAPS_PER_SOURCE, max_urls: int=MAX_URLS_PER_SOURCE) -> list[SitemapEntry]` | function / method |
| [`parse_sitemap`](../../collector/discovery/sitemap.py#L174) | `parse_sitemap(xml_text: str, sitemap_url: str) -> ParsedSitemap` | function / method |
| [`score_sitemap_url`](../../collector/discovery/sitemap.py#L192) | `score_sitemap_url(url: str) -> float` | function / method |
| [`fetch_text_url`](../../collector/discovery/sitemap.py#L223) | `fetch_text_url(url: str, timeout: float=DEFAULT_CONFIG.request_timeout_seconds, max_bytes: int=5000000, user_agent: str=DEFAULT_CONFIG.user_agent) -> str` | function / method |
| [`site_root_url`](../../collector/discovery/sitemap.py#L261) | `site_root_url(source_url: str) -> str` | function / method |
| [`_loc_values`](../../collector/discovery/sitemap.py#L268) | `_loc_values(root: ET.Element, item_name: str, sitemap_url: str) -> list[str]` | function / method |
| [`_child_text`](../../collector/discovery/sitemap.py#L281) | `_child_text(element: ET.Element, child_name: str) -> str` | function / method |
| [`_local_name`](../../collector/discovery/sitemap.py#L289) | `_local_name(tag: str) -> str` | function / method |
| [`_dedupe_urls`](../../collector/discovery/sitemap.py#L293) | `_dedupe_urls(urls: list[str]) -> list[str]` | function / method |
| [`_decode_text`](../../collector/discovery/sitemap.py#L306) | `_decode_text(body: bytes, content_type: str) -> str` | function / method |

<a id="collector-execution-py"></a>

## collector/execution.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ExecutionControl.abort`](../../collector/execution.py#L27) | `abort(self) -> None` | function / method |
| [`ExecutionControl.register`](../../collector/execution.py#L34) | `register(self, future: Future) -> None` | function / method |
| [`ExecutionControl.unregister`](../../collector/execution.py#L41) | `unregister(self, future: Future) -> None` | function / method |
| [`check_execution_active`](../../collector/execution.py#L51) | `check_execution_active() -> None` | function / method |
| [`wait_for_future`](../../collector/execution.py#L57) | `wait_for_future(future: Future)` | function / method |
| [`BoundedThreadExecutor.__init__`](../../collector/execution.py#L83) | `__init__(self, max_workers: int, thread_name_prefix: str='worker')` | function / method |
| [`BoundedThreadExecutor.submit`](../../collector/execution.py#L96) | `submit(self, fn, /, *args, **kwargs)` | function / method |
| [`BoundedThreadExecutor._run`](../../collector/execution.py#L108) | `_run(self)` | function / method |
| [`BoundedThreadExecutor.shutdown`](../../collector/execution.py#L128) | `shutdown(self, wait=True, *, cancel_futures=False)` | function / method |

<a id="collector-extraction-dataset_metadata-py"></a>

## collector/extraction/dataset_metadata.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`normalize_dataset_metadata`](../../collector/extraction/dataset_metadata.py#L20) | `normalize_dataset_metadata(metadata: Mapping[str, object] \| None) -> dict[str, str]` | function / method |
| [`build_dataset_metadata`](../../collector/extraction/dataset_metadata.py#L30) | `build_dataset_metadata(*, title: str='', geography: Iterable[str]=(), date_of_publication: str='', dataset_url: str='', diseases: Iterable[str]=(), size_of_dataset: str='', demographic_information: Iterable[str]=(), sharing_license: str='', modality_of_data: Iterable[str]=(), description_of_dataset: str='') -> dict[str, str]` | function / method |
| [`_value`](../../collector/extraction/dataset_metadata.py#L59) | `_value(value: object) -> str` | function / method |
| [`_values`](../../collector/extraction/dataset_metadata.py#L67) | `_values(values: Iterable[str]) -> str` | function / method |

<a id="collector-extraction-distributions-py"></a>

## collector/extraction/distributions.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`extract_distributions`](../../collector/extraction/distributions.py#L58) | `extract_distributions(page: PageSnapshot) -> list[DistributionCandidate]` | function / method |
| [`guess_format`](../../collector/extraction/distributions.py#L83) | `guess_format(url: str, anchor: str='', mime_type: str='') -> tuple[str, str]` | function / method |
| [`_candidate_from_link`](../../collector/extraction/distributions.py#L103) | `_candidate_from_link(link: LinkCandidate) -> DistributionCandidate \| None` | function / method |
| [`_schema_distribution_candidates`](../../collector/extraction/distributions.py#L146) | `_schema_distribution_candidates(page: PageSnapshot, scoped: tuple[object, ...]) -> list[DistributionCandidate]` | function / method |
| [`_deduplicate_candidates`](../../collector/extraction/distributions.py#L191) | `_deduplicate_candidates(candidates: list[DistributionCandidate]) -> list[DistributionCandidate]` | function / method |
| [`_guess_path_extension`](../../collector/extraction/distributions.py#L205) | `_guess_path_extension(url: str) -> str` | function / method |
| [`_guess_query_extension`](../../collector/extraction/distributions.py#L219) | `_guess_query_extension(url: str) -> str` | function / method |
| [`_looks_like_api`](../../collector/extraction/distributions.py#L229) | `_looks_like_api(url: str, anchor: str='') -> bool` | function / method |

<a id="collector-extraction-errors-py"></a>

## collector/extraction/errors.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ExtractionError.__init__`](../../collector/extraction/errors.py#L7) | `__init__(self, reason: str, *, code: str='extraction_invalid_content') -> None` | function / method |

<a id="collector-extraction-extractor-py"></a>

## collector/extraction/extractor.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_BoundedHTMLParser.__init__`](../../collector/extraction/extractor.py#L30) | `__init__(self, limits: ExtractionLimits) -> None` | function / method |
| [`_BoundedHTMLParser._node`](../../collector/extraction/extractor.py#L36) | `_node(self) -> None` | function / method |
| [`_BoundedHTMLParser._retain`](../../collector/extraction/extractor.py#L41) | `_retain(self, text: str) -> str` | function / method |
| [`_BoundedHTMLParser._start`](../../collector/extraction/extractor.py#L47) | `_start(self, tag: str, attrs: list[tuple[str, str \| None]]) -> None` | function / method |
| [`_BoundedHTMLParser._end`](../../collector/extraction/extractor.py#L58) | `_end(self, tag: str) -> None` | function / method |
| [`_BoundedHTMLParser.handle_decl`](../../collector/extraction/extractor.py#L64) | `handle_decl(self, decl: str) -> None` | function / method |
| [`_BoundedHTMLParser.handle_comment`](../../collector/extraction/extractor.py#L67) | `handle_comment(self, data: str) -> None` | function / method |
| [`_BoundedHTMLParser.unknown_decl`](../../collector/extraction/extractor.py#L70) | `unknown_decl(self, data: str) -> None` | function / method |
| [`_feed_html`](../../collector/extraction/extractor.py#L76) | `_feed_html(parser: _BoundedHTMLParser, html: str) -> None` | function / method |
| [`_PageHTMLParser.__init__`](../../collector/extraction/extractor.py#L92) | `__init__(self, url: str, limits: ExtractionLimits) -> None` | function / method |
| [`_PageHTMLParser.handle_starttag`](../../collector/extraction/extractor.py#L113) | `handle_starttag(self, tag: str, attrs: list[tuple[str, str \| None]]) -> None` | function / method |
| [`_PageHTMLParser.handle_endtag`](../../collector/extraction/extractor.py#L152) | `handle_endtag(self, tag: str) -> None` | function / method |
| [`_PageHTMLParser.handle_data`](../../collector/extraction/extractor.py#L176) | `handle_data(self, data: str) -> None` | function / method |
| [`_PageHTMLParser._handle_meta`](../../collector/extraction/extractor.py#L204) | `_handle_meta(self, attributes: dict[str, str]) -> None` | function / method |
| [`_PageHTMLParser._parse_json_ld`](../../collector/extraction/extractor.py#L252) | `_parse_json_ld(self, script_text: str) -> None` | function / method |
| [`extract_page`](../../collector/extraction/extractor.py#L261) | `extract_page(url: str, html: str, *, limits: ExtractionLimits=DEFAULT_EXTRACTION_LIMITS, expected_identity: dict[str, str] \| None=None) -> PageSnapshot` | function / method |
| [`_publisher_from_json_ld`](../../collector/extraction/extractor.py#L333) | `_publisher_from_json_ld(json_ld_items: list[object]) -> str` | function / method |
| [`_geography_from_json_ld`](../../collector/extraction/extractor.py#L346) | `_geography_from_json_ld(json_ld_items: list[object]) -> list[str]` | function / method |
| [`_date_from_json_ld`](../../collector/extraction/extractor.py#L365) | `_date_from_json_ld(json_ld_items: list[object]) -> str` | function / method |
| [`_license_from_json_ld`](../../collector/extraction/extractor.py#L375) | `_license_from_json_ld(json_ld_items: list[object]) -> str` | function / method |
| [`_size_from_json_ld`](../../collector/extraction/extractor.py#L389) | `_size_from_json_ld(json_ld_items: list[object]) -> str` | function / method |
| [`_modalities_from_json_ld`](../../collector/extraction/extractor.py#L399) | `_modalities_from_json_ld(json_ld_items: list[object]) -> list[str]` | function / method |
| [`_diseases_from_text`](../../collector/extraction/extractor.py#L417) | `_diseases_from_text(value: str) -> list[str]` | function / method |
| [`_demographics_from_text`](../../collector/extraction/extractor.py#L441) | `_demographics_from_text(value: str) -> list[str]` | function / method |
| [`_modalities_from_text`](../../collector/extraction/extractor.py#L451) | `_modalities_from_text(value: str) -> list[str]` | function / method |
| [`_country_values`](../../collector/extraction/extractor.py#L474) | `_country_values(value: object) -> list[str]` | function / method |
| [`_iter_json_objects`](../../collector/extraction/extractor.py#L498) | `_iter_json_objects(value: object) -> list[dict[str, object]]` | function / method |
| [`_root_objects`](../../collector/extraction/extractor.py#L502) | `_root_objects(value: list[object])` | function / method |
| [`_metadata_text`](../../collector/extraction/extractor.py#L506) | `_metadata_text(value: object) -> str` | function / method |
| [`_normalize_text`](../../collector/extraction/extractor.py#L510) | `_normalize_text(value: str) -> str` | function / method |
| [`_dedupe`](../../collector/extraction/extractor.py#L514) | `_dedupe(values: list[str]) -> list[str]` | function / method |
| [`html_to_text`](../../collector/extraction/extractor.py#L518) | `html_to_text(value: str, *, limits: ExtractionLimits=DEFAULT_EXTRACTION_LIMITS) -> str` | function / method |
| [`_TextHTMLParser.__init__`](../../collector/extraction/extractor.py#L531) | `__init__(self, limits: ExtractionLimits) -> None` | function / method |
| [`_TextHTMLParser.handle_starttag`](../../collector/extraction/extractor.py#L535) | `handle_starttag(self, tag: str, attrs: list[tuple[str, str \| None]]) -> None` | function / method |
| [`_TextHTMLParser.handle_endtag`](../../collector/extraction/extractor.py#L538) | `handle_endtag(self, tag: str) -> None` | function / method |
| [`_TextHTMLParser.handle_data`](../../collector/extraction/extractor.py#L541) | `handle_data(self, data: str) -> None` | function / method |
| [`_url_extension`](../../collector/extraction/extractor.py#L551) | `_url_extension(url: str) -> str` | function / method |
| [`_doi_from_json_ld`](../../collector/extraction/extractor.py#L557) | `_doi_from_json_ld(json_ld_items: list[object]) -> str` | function / method |

<a id="collector-extraction-graph-py"></a>

## collector/extraction/graph.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`select_dataset_scope`](../../collector/extraction/graph.py#L26) | `select_dataset_scope(evidence: object, page_url: str, canonical_url: str='', *, citation_doi: str='', expected_identity: dict[str, str] \| None=None, limits: ExtractionLimits=DEFAULT_EXTRACTION_LIMITS) -> DatasetScope` | function / method |
| [`_is_type`](../../collector/extraction/graph.py#L92) | `_is_type(node: dict, name: str) -> bool` | function / method |
| [`_identifiers`](../../collector/extraction/graph.py#L102) | `_identifiers(value: object) -> list[str]` | function / method |
| [`_embedded_objects`](../../collector/extraction/graph.py#L113) | `_embedded_objects(value: object) -> list[dict]` | function / method |
| [`_reference_id`](../../collector/extraction/graph.py#L119) | `_reference_id(value: object, page_url: str) -> str` | function / method |
| [`_matches_url`](../../collector/extraction/graph.py#L128) | `_matches_url(node: dict, urls: set[str], page_url: str) -> bool` | function / method |
| [`_identity_score`](../../collector/extraction/graph.py#L135) | `_identity_score(node: dict, urls: set[str], dois: set[str], entities: set[str], base: str, identifiers: set[str], values: list[str], is_main_entity: bool)` | function / method |
| [`_LocalResolver.__init__`](../../collector/extraction/graph.py#L148) | `__init__(self, index, page_url: str, limits: ExtractionLimits)` | function / method |
| [`_LocalResolver.resolve`](../../collector/extraction/graph.py#L152) | `resolve(self, value, depth: int=0, active: frozenset[str]=frozenset())` | function / method |

<a id="collector-extraction-limits-py"></a>

## collector/extraction/limits.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`ExtractionLimits.__post_init__`](../../collector/extraction/limits.py#L26) | `__post_init__(self) -> None` | function / method |
| [`enforce_limit`](../../collector/extraction/limits.py#L34) | `enforce_limit(value: int, maximum: int, reason: str) -> None` | function / method |
| [`json_objects`](../../collector/extraction/limits.py#L39) | `json_objects(value: object, limits: ExtractionLimits=DEFAULT_EXTRACTION_LIMITS)` | function / method |
| [`load_json_ld`](../../collector/extraction/limits.py#L61) | `load_json_ld(text: str, limits: ExtractionLimits)` | function / method |
| [`_reject_constant`](../../collector/extraction/limits.py#L91) | `_reject_constant(value: str) -> None` | function / method |

<a id="collector-extraction-source_identity-py"></a>

## collector/extraction/source_identity.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`identify_source`](../../collector/extraction/source_identity.py#L24) | `identify_source(url: str) -> SourceIdentity` | function / method |
| [`_kaggle_uploader`](../../collector/extraction/source_identity.py#L38) | `_kaggle_uploader(path: str) -> str` | function / method |

<a id="collector-network-fetch-py"></a>

## collector/network/fetch.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`is_timeout_error`](../../collector/network/fetch.py#L38) | `is_timeout_error(exception: Exception) -> bool` | function / method |
| [`PageFetchError.__init__`](../../collector/network/fetch.py#L48) | `__init__(self, message: str, *, code='repository_unavailable')` | function / method |
| [`fetch_public_html`](../../collector/network/fetch.py#L63) | `fetch_public_html(url: str, timeout: float=DEFAULT_CONFIG.request_timeout_seconds, max_bytes: int=1000000, *, user_agent: str=DEFAULT_CONFIG.user_agent) -> FetchedPage` | function / method |
| [`_ensure_public_http_url`](../../collector/network/fetch.py#L117) | `_ensure_public_http_url(url: str) -> None` | function / method |
| [`_connect_public`](../../collector/network/fetch.py#L142) | `_connect_public(host: str, port: int, timeout: float) -> socket.socket` | function / method |
| [`_connect_public_with_budget`](../../collector/network/fetch.py#L149) | `_connect_public_with_budget(host: str, port: int, timeout: float) -> socket.socket` | function / method |
| [`_PublicHTTPConnection.connect`](../../collector/network/fetch.py#L188) | `connect(self)` | function / method |
| [`_PublicHTTPSConnection.connect`](../../collector/network/fetch.py#L197) | `connect(self)` | function / method |
| [`_PublicHTTPHandler.http_open`](../../collector/network/fetch.py#L212) | `http_open(self, request)` | function / method |
| [`_PublicHTTPSHandler.https_open`](../../collector/network/fetch.py#L217) | `https_open(self, request)` | function / method |
| [`_PublicHTTPRedirectHandler.redirect_request`](../../collector/network/fetch.py#L224) | `redirect_request(self, req, fp, code, msg, headers, newurl)` | function / method |
| [`open_public_http_url`](../../collector/network/fetch.py#L241) | `open_public_http_url(request: Request, *, timeout: float)` | function / method |
| [`_decode_html`](../../collector/network/fetch.py#L266) | `_decode_html(body: bytes, content_type: str) -> str` | function / method |
| [`decode_text_body`](../../collector/network/fetch.py#L270) | `decode_text_body(body: bytes, content_type: str) -> str` | function / method |
| [`decode_json_body`](../../collector/network/fetch.py#L281) | `decode_json_body(body: bytes) -> object` | function / method |

<a id="collector-network-policy-py"></a>

## collector/network/policy.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`is_public_address`](../../collector/network/policy.py#L34) | `is_public_address(address: ipaddress.IPv4Address \| ipaddress.IPv6Address) -> bool` | function / method |

<a id="collector-network-resolver-py"></a>

## collector/network/resolver.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_AddressResolver.__init__`](../../collector/network/resolver.py#L21) | `__init__(self)` | function / method |
| [`_AddressResolver.resolve`](../../collector/network/resolver.py#L25) | `resolve(self, *args, **kwargs)` | function / method |
| [`resolve_addresses`](../../collector/network/resolver.py#L67) | `resolve_addresses(*args, timeout: float, **kwargs)` | function / method |

<a id="collector-network-transport-py"></a>

## collector/network/transport.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_DeadlineReader.__init__`](../../collector/network/transport.py#L26) | `__init__(self, raw, sock, budget: RequestBudget)` | function / method |
| [`_DeadlineReader.readable`](../../collector/network/transport.py#L30) | `readable(self)` | function / method |
| [`_DeadlineReader.readinto`](../../collector/network/transport.py#L33) | `readinto(self, buffer)` | function / method |
| [`_DeadlineReader.close`](../../collector/network/transport.py#L45) | `close(self)` | function / method |
| [`_ResponseSocket.__init__`](../../collector/network/transport.py#L53) | `__init__(self, sock, budget)` | function / method |
| [`_ResponseSocket.makefile`](../../collector/network/transport.py#L56) | `makefile(self, mode)` | function / method |
| [`DeadlineHTTPResponse.__init__`](../../collector/network/transport.py#L66) | `__init__(self, sock, *args, **kwargs)` | function / method |
| [`DeadlineHTTPResponse._bounded`](../../collector/network/transport.py#L72) | `_bounded(self, operation, *args)` | function / method |
| [`DeadlineHTTPResponse.begin`](../../collector/network/transport.py#L84) | `begin(self)` | function / method |
| [`DeadlineHTTPResponse.read`](../../collector/network/transport.py#L87) | `read(self, amt=None)` | function / method |
| [`DeadlineHTTPResponse.read1`](../../collector/network/transport.py#L90) | `read1(self, n=-1)` | function / method |
| [`DeadlineHTTPResponse.readinto`](../../collector/network/transport.py#L93) | `readinto(self, buffer)` | function / method |
| [`_connect_with_deadline`](../../collector/network/transport.py#L97) | `_connect_with_deadline(address, timeout, source_address=None)` | function / method |
| [`_connect_resolved_with_deadline`](../../collector/network/transport.py#L102) | `_connect_resolved_with_deadline(address, timeout, source_address)` | function / method |
| [`_DeadlineConnectionMixin.__init__`](../../collector/network/transport.py#L134) | `__init__(self, *args, **kwargs)` | function / method |
| [`_DeadlineConnectionMixin.send`](../../collector/network/transport.py#L138) | `send(self, data)` | function / method |
| [`DeadlineHTTPSConnection.connect`](../../collector/network/transport.py#L156) | `connect(self)` | function / method |
| [`DeadlineHTTPHandler.http_open`](../../collector/network/transport.py#L170) | `http_open(self, request)` | function / method |
| [`DeadlineHTTPSHandler.https_open`](../../collector/network/transport.py#L175) | `https_open(self, request)` | function / method |
| [`RejectHTTPRedirects.redirect_request`](../../collector/network/transport.py#L185) | `redirect_request(self, req, fp, code, msg, headers, newurl)` | function / method |

<a id="collector-observability-py"></a>

## collector/observability.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`OperationalStreamHandler.handleError`](../../collector/observability.py#L18) | `handleError(self, record) -> None` | function / method |
| [`configure_operational_logging`](../../collector/observability.py#L24) | `configure_operational_logging() -> None` | function / method |
| [`emit_event`](../../collector/observability.py#L35) | `emit_event(event: str, *, outcome: str, duration_seconds: float \| None=None, retry_count: int \| None=None, delay_seconds: float \| None=None, error_category: str \| None=None) -> None` | function / method |
| [`operation_context`](../../collector/observability.py#L60) | `operation_context(*, job_id=None, candidate_id=None, search_id=None, queue=None)` | contextmanager |
| [`measure_operation`](../../collector/observability.py#L75) | `measure_operation(event: str)` | contextmanager |

<a id="collector-repository_search-filtering-py"></a>

## collector/repository_search/filtering.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`filter_repository_results`](../../collector/repository_search/filtering.py#L14) | `filter_repository_results(results: Iterable[RepositorySearchResult]) -> tuple[list[RepositorySearchResult], int]` | function / method |
| [`_valid_provider_text`](../../collector/repository_search/filtering.py#L60) | `_valid_provider_text(value: str) -> bool` | function / method |
| [`_http_url`](../../collector/repository_search/filtering.py#L71) | `_http_url(value: str) -> str` | function / method |
| [`_text`](../../collector/repository_search/filtering.py#L78) | `_text(value: object) -> str` | function / method |

<a id="collector-repository_search-models-py"></a>

## collector/repository_search/models.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`RepositorySearchProvider.search`](../../collector/repository_search/models.py#L65) | `search(self, query: str) -> RepositorySearchResponse` | function / method |

<a id="collector-repository_search-providers-datacite-py"></a>

## collector/repository_search/providers/datacite.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`DataCiteRepositorySearchProvider.__init__`](../../collector/repository_search/providers/datacite.py#L122) | `__init__(self, fetch_json: JsonFetcher \| None=None, page_size: int=10) -> None` | function / method |
| [`DataCiteRepositorySearchProvider.search`](../../collector/repository_search/providers/datacite.py#L130) | `search(self, query: str) -> RepositorySearchResponse` | function / method |
| [`DataCiteRepositorySearchProvider._search_url`](../../collector/repository_search/providers/datacite.py#L162) | `_search_url(self, query: str) -> str` | function / method |
| [`_datacite_result`](../../collector/repository_search/providers/datacite.py#L172) | `_datacite_result(item: dict[object, object]) -> RepositorySearchResult \| None` | function / method |
| [`_search_result_metadata`](../../collector/repository_search/providers/datacite.py#L208) | `_search_result_metadata(attributes: dict[object, object], *, title: str, url: str, date: str, description: str, subjects: list[str]) -> dict[str, str]` | function / method |
| [`_metadata_values`](../../collector/repository_search/providers/datacite.py#L232) | `_metadata_values(values: Iterable[str]) -> str` | function / method |
| [`_geography`](../../collector/repository_search/providers/datacite.py#L242) | `_geography(attributes: dict[object, object]) -> list[str]` | function / method |
| [`_diseases`](../../collector/repository_search/providers/datacite.py#L277) | `_diseases(subjects: list[str], searchable_text: str) -> list[str]` | function / method |
| [`_dataset_sizes`](../../collector/repository_search/providers/datacite.py#L295) | `_dataset_sizes(attributes: dict[object, object], description: str) -> list[str]` | function / method |
| [`_demographic_information`](../../collector/repository_search/providers/datacite.py#L315) | `_demographic_information(searchable_text: str) -> list[str]` | function / method |
| [`_sharing_license`](../../collector/repository_search/providers/datacite.py#L320) | `_sharing_license(attributes: dict[object, object]) -> list[str]` | function / method |
| [`_data_modalities`](../../collector/repository_search/providers/datacite.py#L339) | `_data_modalities(attributes: dict[object, object], searchable_text: str) -> list[str]` | function / method |
| [`_modalities_from_format`](../../collector/repository_search/providers/datacite.py#L352) | `_modalities_from_format(data_format: str) -> list[str]` | function / method |
| [`_metadata_text_values`](../../collector/repository_search/providers/datacite.py#L371) | `_metadata_text_values(value: object, *, keys: tuple[str, ...]=()) -> list[str]` | function / method |
| [`_metadata_dict_items`](../../collector/repository_search/providers/datacite.py#L402) | `_metadata_dict_items(value: object) -> list[dict[object, object]]` | function / method |
| [`_geo_point`](../../collector/repository_search/providers/datacite.py#L410) | `_geo_point(value: object) -> str` | function / method |
| [`_geo_box`](../../collector/repository_search/providers/datacite.py#L426) | `_geo_box(value: object) -> str` | function / method |
| [`_coordinate`](../../collector/repository_search/providers/datacite.py#L441) | `_coordinate(value: object, *, maximum: int) -> str` | function / method |
| [`_normalize_for_matching`](../../collector/repository_search/providers/datacite.py#L455) | `_normalize_for_matching(value: str) -> str` | function / method |
| [`_contains_term`](../../collector/repository_search/providers/datacite.py#L459) | `_contains_term(normalized_text: str, normalized_term: str) -> bool` | function / method |
| [`_title`](../../collector/repository_search/providers/datacite.py#L463) | `_title(attributes: dict[object, object]) -> str` | function / method |
| [`_description`](../../collector/repository_search/providers/datacite.py#L477) | `_description(attributes: dict[object, object]) -> str` | function / method |
| [`_publisher`](../../collector/repository_search/providers/datacite.py#L499) | `_publisher(attributes: dict[object, object]) -> str` | function / method |
| [`_date`](../../collector/repository_search/providers/datacite.py#L507) | `_date(attributes: dict[object, object]) -> str` | function / method |
| [`_doi`](../../collector/repository_search/providers/datacite.py#L541) | `_doi(item: dict[object, object], attributes: dict[object, object]) -> str` | function / method |
| [`_doi_url`](../../collector/repository_search/providers/datacite.py#L549) | `_doi_url(doi: str) -> str` | function / method |
| [`_subjects`](../../collector/repository_search/providers/datacite.py#L553) | `_subjects(attributes: dict[object, object]) -> list[str]` | function / method |

<a id="collector-repository_search-service-py"></a>

## collector/repository_search/service.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`search_repository_metadata`](../../collector/repository_search/service.py#L29) | `search_repository_metadata(query: str, providers: Iterable[RepositorySearchProvider] \| None=None) -> RepositorySearchResponse` | function / method |
| [`classify_repository_result`](../../collector/repository_search/service.py#L81) | `classify_repository_result(result: RepositorySearchResult, classifier: RepositoryResultClassifier) -> RepositorySearchResult` | function / method |
| [`_repository_result_page`](../../collector/repository_search/service.py#L96) | `_repository_result_page(result: RepositorySearchResult) -> PageSnapshot` | function / method |
| [`_metadata_text`](../../collector/repository_search/service.py#L134) | `_metadata_text(value: str, *, fallback: str='') -> str` | function / method |
| [`_metadata_items`](../../collector/repository_search/service.py#L138) | `_metadata_items(value: str) -> tuple[str, ...]` | function / method |

<a id="collector-storage-metadata-py"></a>

## collector/storage/metadata.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`normalize_doi`](../../collector/storage/metadata.py#L15) | `normalize_doi(value: object) -> str` | function / method |
| [`metadata_evidence`](../../collector/storage/metadata.py#L23) | `metadata_evidence(dataset: PageSnapshot \| CollectedDataset, *, kind: str, source_url: str) -> dict[str, object]` | function / method |
| [`enrich_from_repository`](../../collector/storage/metadata.py#L37) | `enrich_from_repository(dataset: CollectedDataset, candidate: dict[str, object]) -> CollectedDataset` | function / method |

<a id="collector-storage-models-py"></a>

## collector/storage/models.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`PageSnapshot.__post_init__`](../../collector/storage/models.py#L65) | `__post_init__(self) -> None` | function / method |
| [`PageSnapshot.dataset_metadata`](../../collector/storage/models.py#L98) | `dataset_metadata(self) -> dict[str, str]` | function / method |
| [`_first_text`](../../collector/storage/models.py#L115) | `_first_text(*values: str) -> str` | function / method |
| [`_normalized_values`](../../collector/storage/models.py#L119) | `_normalized_values(values: tuple[str, ...]) -> tuple[str, ...]` | function / method |
| [`ValidationResult.__post_init__`](../../collector/storage/models.py#L186) | `__post_init__(self) -> None` | function / method |
| [`CollectedDataset.__post_init__`](../../collector/storage/models.py#L232) | `__post_init__(self) -> None` | function / method |

<a id="collector-url_utils-py"></a>

## collector/url_utils.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`canonicalize_url`](../../collector/url_utils.py#L8) | `canonicalize_url(url: str, base_url: str \| None=None) -> str` | function / method |
| [`normalize_http_url`](../../collector/url_utils.py#L22) | `normalize_http_url(value: str, base_url: str \| None=None) -> str \| None` | function / method |
| [`require_http_url`](../../collector/url_utils.py#L54) | `require_http_url(value: str) -> str` | function / method |
| [`select_dataset_url`](../../collector/url_utils.py#L61) | `select_dataset_url(page_url: str, canonical_href: str='') -> str` | function / method |
| [`same_domain`](../../collector/url_utils.py#L73) | `same_domain(left_url: str, right_url: str) -> bool` | function / method |

<a id="collector-validation-distributions-py"></a>

## collector/validation/distributions.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`validate_distribution`](../../collector/validation/distributions.py#L34) | `validate_distribution(distribution: DistributionCandidate, timeout: float=DEFAULT_CONFIG.request_timeout_seconds, max_sample_bytes: int=DEFAULT_CONFIG.max_sample_bytes, probe: ProbeFunction \| None=None, user_agent: str=DEFAULT_CONFIG.user_agent) -> ValidationResult` | function / method |
| [`page_access_diagnostic`](../../collector/validation/distributions.py#L88) | `page_access_diagnostic(html: str) -> Diagnostic \| None` | function / method |
| [`probe_url`](../../collector/validation/distributions.py#L105) | `probe_url(url: str, method: str, timeout: float, max_bytes: int, headers: dict[str, str] \| None=None, user_agent: str=DEFAULT_CONFIG.user_agent) -> HTTPProbe` | function / method |
| [`_needs_partial_get`](../../collector/validation/distributions.py#L170) | `_needs_partial_get(probe: HTTPProbe) -> bool` | function / method |
| [`_response_status`](../../collector/validation/distributions.py#L177) | `_response_status(probe: HTTPProbe, format_name: str) -> tuple[ValidationStatus, str]` | function / method |
| [`_access_barrier`](../../collector/validation/distributions.py#L281) | `_access_barrier(text: str) -> tuple[ValidationStatus, str] \| None` | function / method |
| [`_AccessPage.__init__`](../../collector/validation/distributions.py#L311) | `__init__(self) -> None` | function / method |
| [`_AccessPage.handle_starttag`](../../collector/validation/distributions.py#L319) | `handle_starttag(self, tag: str, attrs: list[tuple[str, str \| None]]) -> None` | function / method |
| [`_AccessPage.handle_endtag`](../../collector/validation/distributions.py#L334) | `handle_endtag(self, tag: str) -> None` | function / method |
| [`_AccessPage.handle_data`](../../collector/validation/distributions.py#L340) | `handle_data(self, data: str) -> None` | function / method |
| [`_prefix_range`](../../collector/validation/distributions.py#L345) | `_prefix_range(probe: HTTPProbe) -> re.Match \| None` | function / method |
| [`_sample_is_truncated`](../../collector/validation/distributions.py#L359) | `_sample_is_truncated(probe: HTTPProbe) -> bool` | function / method |
| [`_total_size`](../../collector/validation/distributions.py#L370) | `_total_size(probe: HTTPProbe, head: HTTPProbe) -> int \| None` | function / method |
| [`_validated_format`](../../collector/validation/distributions.py#L393) | `_validated_format(distribution: DistributionCandidate, content_type: str, content_disposition: str, probe: HTTPProbe) -> str` | function / method |
| [`_format_from_body_sample`](../../collector/validation/distributions.py#L419) | `_format_from_body_sample(sample: bytes, truncated: bool=False) -> str` | function / method |
| [`_decode_tabular_sample`](../../collector/validation/distributions.py#L475) | `_decode_tabular_sample(sample: bytes, truncated: bool) -> str \| None` | function / method |
| [`_plausible_table`](../../collector/validation/distributions.py#L495) | `_plausible_table(text: str, delimiter: str, truncated: bool) -> bool` | function / method |
| [`_header`](../../collector/validation/distributions.py#L524) | `_header(probe: HTTPProbe, name: str) -> str` | function / method |
| [`_parse_content_length`](../../collector/validation/distributions.py#L528) | `_parse_content_length(value: str) -> int \| None` | function / method |

<a id="collector-validation-json_sample-py"></a>

## collector/validation/json_sample.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`reject_json_constant`](../../collector/validation/json_sample.py#L24) | `reject_json_constant(value: str) -> None` | function / method |
| [`read_json_prefix`](../../collector/validation/json_sample.py#L29) | `read_json_prefix(sample: bytes) -> object` | function / method |
| [`_PrefixReader.__init__`](../../collector/validation/json_sample.py#L47) | `__init__(self, text: str)` | function / method |
| [`_PrefixReader.whitespace`](../../collector/validation/json_sample.py#L52) | `whitespace(self) -> None` | function / method |
| [`_PrefixReader.value`](../../collector/validation/json_sample.py#L56) | `value(self, depth: int) -> tuple[object, bool]` | function / method |
| [`_PrefixReader.container`](../../collector/validation/json_sample.py#L84) | `container(self, depth: int, mapping: bool) -> tuple[object, bool]` | function / method |

<a id="scripts-api_client-py"></a>

## scripts/api_client.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`APIError.__init__`](../../scripts/api_client.py#L54) | `__init__(self, message, *, status=None, retry_after=None)` | function / method |
| [`NoRedirect.redirect_request`](../../scripts/api_client.py#L61) | `redirect_request(self, req, fp, code, msg, headers, newurl)` | function / method |
| [`_DeadlineReader.__init__`](../../scripts/api_client.py#L67) | `__init__(self, stream, sock, deadline)` | function / method |
| [`_DeadlineReader.read1`](../../scripts/api_client.py#L70) | `read1(self, size=-1)` | function / method |
| [`_DeadlineReader.read`](../../scripts/api_client.py#L77) | `read(self, size=-1)` | function / method |
| [`_DeadlineReader.readinto`](../../scripts/api_client.py#L87) | `readinto(self, buffer)` | function / method |
| [`_DeadlineReader.readline`](../../scripts/api_client.py#L93) | `readline(self, limit=-1)` | function / method |
| [`_DeadlineReader.__getattr__`](../../scripts/api_client.py#L104) | `__getattr__(self, name)` | function / method |
| [`_DeadlineResponse.__init__`](../../scripts/api_client.py#L109) | `__init__(self, sock, *args, deadline, **kwargs)` | function / method |
| [`_DeadlineConnection.__init__`](../../scripts/api_client.py#L115) | `__init__(self, *args, deadline, **kwargs)` | function / method |
| [`_DeadlineConnection._remaining`](../../scripts/api_client.py#L121) | `_remaining(self)` | function / method |
| [`_DeadlineConnection._connect_with_deadline`](../../scripts/api_client.py#L127) | `_connect_with_deadline(self, address, timeout, source_address=None)` | function / method |
| [`_DeadlineConnection.send`](../../scripts/api_client.py#L154) | `send(self, data)` | function / method |
| [`_HTTPSConnection.connect`](../../scripts/api_client.py#L172) | `connect(self)` | function / method |
| [`_HTTPHandler.http_open`](../../scripts/api_client.py#L187) | `http_open(self, req)` | function / method |
| [`_HTTPSHandler.https_open`](../../scripts/api_client.py#L192) | `https_open(self, req)` | function / method |
| [`_retry_after`](../../scripts/api_client.py#L200) | `_retry_after(value)` | function / method |
| [`_private_write`](../../scripts/api_client.py#L211) | `_private_write(path, writer)` | function / method |
| [`Client.__init__`](../../scripts/api_client.py#L227) | `__init__(self, base_url, *, origin='', cookie_file=None, timeout=HTTP_TIMEOUT_SECONDS)` | function / method |
| [`Client.redact`](../../scripts/api_client.py#L250) | `redact(self, value)` | function / method |
| [`Client.request`](../../scripts/api_client.py#L257) | `request(self, method, path, *, payload=None, key=None, deadline=None)` | function / method |
| [`_invalid_constant`](../../scripts/api_client.py#L307) | `_invalid_constant(value)` | function / method |
| [`save_report`](../../scripts/api_client.py#L311) | `save_report(path, report)` | function / method |
| [`positive_number`](../../scripts/api_client.py#L323) | `positive_number(value)` | function / method |
| [`client_settings`](../../scripts/api_client.py#L330) | `client_settings(path)` | function / method |
| [`parse_args`](../../scripts/api_client.py#L357) | `parse_args(argv=None)` | function / method |
| [`_validate_client_files`](../../scripts/api_client.py#L434) | `_validate_client_files()` | function / method |
| [`_uuid`](../../scripts/api_client.py#L447) | `_uuid(value)` | function / method |
| [`_snapshot`](../../scripts/api_client.py#L456) | `_snapshot(value, *, search_id=None)` | function / method |
| [`_command`](../../scripts/api_client.py#L475) | `_command(value, client, *, search_id=None)` | function / method |
| [`_datasets`](../../scripts/api_client.py#L494) | `_datasets(value, requested)` | function / method |
| [`client_lock`](../../scripts/api_client.py#L504) | `client_lock()` | contextmanager |
| [`_recovery_context`](../../scripts/api_client.py#L539) | `_recovery_context(client, args)` | function / method |
| [`_read_pending_search`](../../scripts/api_client.py#L552) | `_read_pending_search()` | function / method |
| [`_check_pending_search`](../../scripts/api_client.py#L575) | `_check_pending_search(pending, client, args)` | function / method |
| [`_save_pending_search`](../../scripts/api_client.py#L585) | `_save_pending_search(pending)` | function / method |
| [`_interruption_hint`](../../scripts/api_client.py#L592) | `_interruption_hint(report)` | function / method |
| [`startup_checks`](../../scripts/api_client.py#L605) | `startup_checks(client, *, processing, access_mode='local')` | function / method |
| [`run`](../../scripts/api_client.py#L645) | `run(args)` | function / method |
| [`run.<local>.persist`](../../scripts/api_client.py#L650) | `persist()` | function / method |
| [`main`](../../scripts/api_client.py#L773) | `main(argv=None)` | function / method |

<a id="scripts-setup_api-py"></a>

## scripts/setup_api.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`_read_values`](../../scripts/setup_api.py#L20) | `_read_values(path)` | function / method |
| [`_parse_values`](../../scripts/setup_api.py#L30) | `_parse_values(content, filename)` | function / method |
| [`_port`](../../scripts/setup_api.py#L53) | `_port(value)` | function / method |
| [`_replace_settings`](../../scripts/setup_api.py#L63) | `_replace_settings(template, replacements)` | function / method |
| [`_create_private`](../../scripts/setup_api.py#L76) | `_create_private(path, content)` | function / method |
| [`validate_local`](../../scripts/setup_api.py#L87) | `validate_local(values)` | function / method |
| [`initialize`](../../scripts/setup_api.py#L102) | `initialize(root, *, port=None)` | function / method |
| [`main`](../../scripts/setup_api.py#L153) | `main(argv=None)` | function / method |

<a id="scripts-start_api-py"></a>

## scripts/start_api.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`local_environment`](../../scripts/start_api.py#L17) | `local_environment(values)` | function / method |
| [`start`](../../scripts/start_api.py#L43) | `start(root=PROJECT_ROOT, *, application='app.main:app')` | function / method |
| [`main`](../../scripts/start_api.py#L106) | `main()` | function / method |

<a id="search_lab-backend-app-py"></a>

## search_lab/backend/app.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`principal`](../../search_lab/backend/app.py#L24) | `principal(request: Request, response: Response)` | async |
| [`create_app`](../../search_lab/backend/app.py#L54) | `create_app(settings=None)` | function / method |
| [`create_app.<local>.lifespan`](../../search_lab/backend/app.py#L55) | `lifespan(application)` | asynccontextmanager |
| [`create_app.<local>.no_cache`](../../search_lab/backend/app.py#L75) | `no_cache(request, call_next)` | async |
| [`create_app.<local>.config`](../../search_lab/backend/app.py#L81) | `config()` | async |
| [`create_app.<local>.searches`](../../search_lab/backend/app.py#L89) | `searches(request: Request, owner: Owner, q: str=Query(default='', max_length=200), origin: Literal['database', 'online']=None, limit: int=Query(default=25, ge=1, le=100), cursor: str=Query(default=None, max_length=500))` | async |
| [`create_app.<local>.observation`](../../search_lab/backend/app.py#L109) | `observation(search_id, request, owner)` | async |
| [`create_app.<local>.detail`](../../search_lab/backend/app.py#L148) | `detail(search_id: UUID, request: Request, owner: Owner)` | async |
| [`create_app.<local>.capture`](../../search_lab/backend/app.py#L152) | `capture(search_id: UUID, notes: SnapshotCaptureRequest, request: Request, owner: Owner)` | async |
| [`create_app.<local>.snapshots`](../../search_lab/backend/app.py#L164) | `snapshots(request: Request, owner: Owner)` | async |
| [`create_app.<local>.read_snapshot`](../../search_lab/backend/app.py#L168) | `read_snapshot(request, owner, identifier)` | function / method |
| [`create_app.<local>.snapshot`](../../search_lab/backend/app.py#L176) | `snapshot(identifier: UUID, request: Request, owner: Owner)` | async |
| [`create_app.<local>.comparison`](../../search_lab/backend/app.py#L180) | `comparison(before: UUID, after: UUID, request: Request, owner: Owner)` | async |

<a id="search_lab-backend-attempts-py"></a>

## search_lab/backend/attempts.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`group_attempts`](../../search_lab/backend/attempts.py#L8) | `group_attempts(trace, claims)` | function / method |

<a id="search_lab-backend-comparison-py"></a>

## search_lab/backend/comparison.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`candidates`](../../search_lab/backend/comparison.py#L4) | `candidates(snapshot)` | function / method |
| [`compare`](../../search_lab/backend/comparison.py#L25) | `compare(left, right)` | function / method |

<a id="search_lab-backend-history-py"></a>

## search_lab/backend/history.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`decode_cursor`](../../search_lab/backend/history.py#L15) | `decode_cursor(value)` | function / method |
| [`History.__init__`](../../search_lab/backend/history.py#L26) | `__init__(self, database_url)` | function / method |
| [`History._configure`](../../search_lab/backend/history.py#L36) | `_configure(connection)` | staticmethod |
| [`History.open`](../../search_lab/backend/history.py#L41) | `open(self)` | async |
| [`History.close`](../../search_lab/backend/history.py#L45) | `close(self)` | async |
| [`History.connection`](../../search_lab/backend/history.py#L48) | `connection(self)` | asynccontextmanager |
| [`History.list_searches`](../../search_lab/backend/history.py#L57) | `list_searches(self, owner_id, *, query='', origin=None, limit=25, cursor=None)` | async |
| [`History.owns_search`](../../search_lab/backend/history.py#L99) | `owns_search(self, owner_id, search_id)` | async |
| [`History.method_claims`](../../search_lab/backend/history.py#L109) | `method_claims(self, job_ids)` | async |

<a id="search_lab-backend-settings-py"></a>

## search_lab/backend/settings.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`evidence_directory`](../../search_lab/backend/settings.py#L13) | `evidence_directory() -> Path` | function / method |
| [`local_api_url`](../../search_lab/backend/settings.py#L18) | `local_api_url(value: str) -> str` | function / method |
| [`Settings.configured`](../../search_lab/backend/settings.py#L39) | `configured(cls)` | classmethod |

<a id="search_lab-backend-snapshots-py"></a>

## search_lab/backend/snapshots.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`checksum`](../../search_lab/backend/snapshots.py#L14) | `checksum(document)` | function / method |
| [`candidate_observation`](../../search_lab/backend/snapshots.py#L21) | `candidate_observation(observation, candidate_id)` | function / method |
| [`Snapshots.__init__`](../../search_lab/backend/snapshots.py#L62) | `__init__(self, directory)` | function / method |
| [`Snapshots.owner_directory`](../../search_lab/backend/snapshots.py#L65) | `owner_directory(self, owner_id)` | function / method |
| [`Snapshots.create`](../../search_lab/backend/snapshots.py#L68) | `create(self, owner_id, observation, notes, candidate_id=None)` | function / method |
| [`Snapshots.read`](../../search_lab/backend/snapshots.py#L102) | `read(self, owner_id, identifier)` | function / method |
| [`Snapshots.list`](../../search_lab/backend/snapshots.py#L110) | `list(self, owner_id)` | function / method |

<a id="search_lab-scenarios-experiment-py"></a>

## search_lab/scenarios/experiment.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`target_database`](../../search_lab/scenarios/experiment.py#L21) | `target_database(name)` | function / method |
| [`main`](../../search_lab/scenarios/experiment.py#L30) | `main()` | function / method |

<a id="search_lab-scenarios-run-py"></a>

## search_lab/scenarios/run.py

| Definition | Signature | Kind |
| --- | --- | --- |
| [`fingerprint`](../../search_lab/scenarios/run.py#L32) | `fingerprint()` | function / method |
| [`public_evidence`](../../search_lab/scenarios/run.py#L53) | `public_evidence(value)` | function / method |
| [`execute`](../../search_lab/scenarios/run.py#L69) | `execute(mode, url, *, offline_json=None, include_ai=False)` | function / method |
| [`main`](../../search_lab/scenarios/run.py#L146) | `main()` | function / method |
