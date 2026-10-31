# Database function audit

Snapshot of the structural refactor on **31 October 2026**. All 163 existing DB functions and methods are inventoried below. Signatures, return expressions, SQL references and connection/transaction ownership were extracted from the pre-refactor source; destinations refer to the new layout. Caller lists cover statically resolved direct calls, not every callback, fixture injection or dynamically selected module. An empty list does not mean a function is unused. Table lists include resolved DB helper calls; caller-supplied SQL and dynamic SQL identifiers remain explicitly subject to caller context. No runtime data or credentials are included.

## `catalog/datasets.py`

<details>
<summary><code>save_collected_datasets</code> — Upsert a batch of datasets in one transaction without changing job state.</summary>

- Source: [catalog/datasets.py:29](../../backend/app/db/catalog/datasets.py#L29).
- Arguments: `source_url: str, datasets: list[CollectedDataset], collection_job_id: int \| None=None`.
- Return annotation: `list[CollectedDataset]`.
- Return expressions: `[await _save_collected_dataset(connection, source_url, dataset, collection_job_id) for dataset in datasets]`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collected_distributions`, `dataset_discovery_observations`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.datasets._save_collected_dataset`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>get_collected_datasets</code> — Resolve explicit public catalog IDs independently of catalog pagination.</summary>

- Source: [catalog/datasets.py:54](../../backend/app/db/catalog/datasets.py#L54).
- Arguments: `dataset_ids: list[int]`.
- Return annotation: `list[CollectedDataset]`.
- Return expressions: `[]; await _datasets_with_distributions(connection, rows)`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collected_distributions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.datasets._datasets_with_distributions`, `connection._fetchall`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: `app.api.routes.catalog.get_catalog_datasets_by_id`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_datasets_with_distributions</code> — Load distribution rows in bulk and rehydrate dataset aggregates.</summary>

- Source: [catalog/datasets.py:69](../../backend/app/db/catalog/datasets.py#L69).
- Arguments: `connection, dataset_rows`.
- Return annotation: `list[CollectedDataset]`.
- Return expressions: `[]; [_collected_dataset_from_rows(row, by_id.get(int(row['id']), [])) for row in dataset_rows]`.
- Tables referenced directly or through resolved DB helpers: `collected_distributions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.datasets._collected_dataset_from_rows`, `connection._fetchall`.
- Statically resolved callers: `app.db.catalog.datasets.get_collected_datasets`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_save_collected_dataset</code> — Upsert one dataset aggregate using the caller's active transaction.</summary>

- Source: [catalog/datasets.py:86](../../backend/app/db/catalog/datasets.py#L86).
- Arguments: `connection: AsyncConnection[DictRow], source_url: str, dataset: CollectedDataset, collection_job_id: int \| None`.
- Return annotation: `CollectedDataset`.
- Return expressions: `_collected_dataset_from_rows(dataset_row, await _fetch_collected_distribution_rows(connection, dataset_id))`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collected_distributions`, `dataset_discovery_observations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.datasets._collected_dataset_from_rows`, `catalog.datasets._upsert_collected_dataset`, `catalog.distributions._fetch_collected_distribution_rows`, `catalog.distributions._upsert_collected_distributions`, `catalog.observations._insert_dataset_discovery_observation`.
- Statically resolved callers: `app.db.catalog.datasets.save_collected_datasets`, `app.db.collection.completion.complete_collection_job`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_upsert_collected_dataset</code> — Deduplicate by the normalized dataset URL and refresh non-empty metadata.</summary>

- Source: [catalog/datasets.py:119](../../backend/app/db/catalog/datasets.py#L119).
- Arguments: `connection: AsyncConnection[DictRow], source_url: str, dataset: CollectedDataset`.
- Return annotation: `Row`.
- Return expressions: `row`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `serialization._serialize_geography`, `serialization._serialize_signals`.
- Statically resolved callers: `app.db.catalog.datasets._save_collected_dataset`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_collected_dataset_from_rows</code> — Rehydrate one dataset aggregate and only attempted validations.</summary>

- Source: [catalog/datasets.py:230](../../backend/app/db/catalog/datasets.py#L230).
- Arguments: `dataset_row: Row, distribution_rows: list[Row]`.
- Return annotation: `CollectedDataset`.
- Return expressions: `CollectedDataset(dataset_url=str(dataset_row['dataset_url']), date_of_publication=str(dataset_row['date_of_publication']), sharing_license=str(dataset_row['sharing_license']), doi=str(dataset_row['doi']), metadata_provenance=_deserialize_signals(dataset_row['metadata_provenance'], 'collected_datasets.metadata_provenance'), record_identity=_deserialize_signals(dataset_row['record_identity'], 'collected_datasets.record_identity'), title=str(dataset_row['title']), description=str(dataset_row['description']), publisher=str(dataset_row['publisher']), hosting_platform=str(dataset_row['hosting_platform']), uploader=str(dataset_row['uploader']), geography=tuple(_deserialize_geography(dataset_row['geography'])), dataset_signals=_deserialize_signals(dataset_row['dataset_signals'], 'collected_datasets.dataset_signals'), distributions=distributions, discovery_method=str(dataset_row['discovery_method']), validation_results=validation_results, source_url=str(dataset_row['source_url']), database_id=int(dataset_row['id']), first_seen_at=_format_timestamp(dataset_row['first_seen_at']), last_seen_at=_format_timestamp(dataset_row['last_seen_at']), updated_at=_format_timestamp(dataset_row['updated_at']))`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._deserialize_geography`, `serialization._deserialize_signals`, `serialization._format_optional_timestamp`, `serialization._format_timestamp`.
- Statically resolved callers: `app.db.catalog.datasets._datasets_with_distributions`, `app.db.catalog.datasets._save_collected_dataset`, `app.db.catalog.search.search_collected_datasets`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `catalog/distributions.py`

<details>
<summary><code>_validation_results_by_distribution_key</code> — Index validations by URL and format, rejecting duplicate evidence.</summary>

- Source: [catalog/distributions.py:13](../../backend/app/db/catalog/distributions.py#L13).
- Arguments: `validation_results: list[ValidationResult]`.
- Return annotation: `dict[tuple[str, str], ValidationResult]`.
- Return expressions: `validation_by_distribution_key`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.distributions._upsert_collected_distributions`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_orphan_validation_result_error</code> — Describe validation evidence that has no matching distribution.</summary>

- Source: [catalog/distributions.py:31](../../backend/app/db/catalog/distributions.py#L31).
- Arguments: `dataset: CollectedDataset, validation_keys: set[tuple[str, str]]`.
- Return annotation: `ValueError \| None`.
- Return expressions: `None; ValueError(f'Validation result does not match any distribution for dataset {dataset.dataset_url!r}: {formatted_keys}.')`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.distributions._upsert_collected_distributions`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_upsert_collected_distributions</code> — Validate evidence links and upsert each currently observed distribution.</summary>

- Source: [catalog/distributions.py:53](../../backend/app/db/catalog/distributions.py#L53).
- Arguments: `connection: AsyncConnection[DictRow], dataset_id: int, dataset: CollectedDataset`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `collected_distributions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.distributions._orphan_validation_result_error`, `catalog.distributions._upsert_collected_distribution`, `catalog.distributions._validation_results_by_distribution_key`.
- Statically resolved callers: `app.db.catalog.datasets._save_collected_dataset`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_upsert_collected_distribution</code> — Deduplicate a distribution by dataset, URL, and format.</summary>

- Source: [catalog/distributions.py:83](../../backend/app/db/catalog/distributions.py#L83).
- Arguments: `connection: AsyncConnection[DictRow], dataset_id: int, distribution: DistributionCandidate, validation: ValidationResult \| None`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `collected_distributions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._serialize_signals`.
- Statically resolved callers: `app.db.catalog.distributions._upsert_collected_distributions`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_fetch_collected_distribution_rows</code> — Read distribution evidence for one saved dataset, ranked by extraction score.</summary>

- Source: [catalog/distributions.py:208](../../backend/app/db/catalog/distributions.py#L208).
- Arguments: `connection: AsyncConnection[DictRow], dataset_id: int`.
- Return annotation: `list[Row]`.
- Return expressions: `await _fetchall(connection, '\n        SELECT *\n        FROM collected_distributions\n        WHERE dataset_id = %s\n        ORDER BY probability DESC, url\n        ', (dataset_id,))`.
- Tables referenced directly or through resolved DB helpers: `collected_distributions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`.
- Statically resolved callers: `app.db.catalog.datasets._save_collected_dataset`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `catalog/observations.py`

<details>
<summary><code>list_dataset_discovery_observations</code> — Read dataset discovery provenance, optionally restricted to one dataset.</summary>

- Source: [catalog/observations.py:13](../../backend/app/db/catalog/observations.py#L13).
- Arguments: `dataset_id: int \| None=None`.
- Return annotation: `list[dict[str, int \| str \| None]]`.
- Return expressions: `[_dataset_discovery_observation_to_dict(row) for row in rows]`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `dataset_discovery_observations`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.observations._dataset_discovery_observation_to_dict`, `catalog.observations._select_dataset_discovery_observations`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_insert_dataset_discovery_observation</code> — Append one observation even when the dataset URL already existed.</summary>

- Source: [catalog/observations.py:23](../../backend/app/db/catalog/observations.py#L23).
- Arguments: `connection: AsyncConnection[DictRow], dataset_id: int, source_url: str, discovery_method: str, collection_job_id: int \| None`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `dataset_discovery_observations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.datasets._save_collected_dataset`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_select_dataset_discovery_observations</code> — Query ordered provenance rows on the caller connection.</summary>

- Source: [catalog/observations.py:43](../../backend/app/db/catalog/observations.py#L43).
- Arguments: `connection: AsyncConnection[DictRow], dataset_id: int \| None`.
- Return annotation: `list[Row]`.
- Return expressions: `await _fetchall(connection, sql, parameters)`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `dataset_discovery_observations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`.
- Statically resolved callers: `app.db.catalog.observations.list_dataset_discovery_observations`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_dataset_discovery_observation_to_dict</code> — Serialize a persisted provenance row and its timestamp.</summary>

- Source: [catalog/observations.py:64](../../backend/app/db/catalog/observations.py#L64).
- Arguments: `row: Row`.
- Return annotation: `dict[str, int \| str \| None]`.
- Return expressions: `{'id': int(row['id']), 'dataset_id': int(row['dataset_id']), 'dataset_url': str(row['dataset_url']), 'collection_job_id': int(row['collection_job_id']) if row['collection_job_id'] is not None else None, 'source_url': str(row['source_url']), 'discovery_method': str(row['discovery_method']), 'observed_at': _format_timestamp(row['observed_at'])}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._format_timestamp`.
- Statically resolved callers: `app.db.catalog.observations.list_dataset_discovery_observations`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `catalog/search.py`

<details>
<summary><code>normalize_dataset_search_query</code> — Remove catalog-generic terms before PostgreSQL full-text search.</summary>

- Source: [catalog/search.py:21](../../backend/app/db/catalog/search.py#L21).
- Arguments: `query: str`.
- Return annotation: `str`.
- Return expressions: `' '.join(meaningful_terms)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.workers.search.discovery.lookup_local`, `tests.test_collector_routes.test_normalize_dataset_search_query`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>search_collected_datasets</code> — Search persisted metadata with weighted PostgreSQL full-text ranking.</summary>

- Source: [catalog/search.py:42](../../backend/app/db/catalog/search.py#L42).
- Arguments: `query: str, limit: int=10`.
- Return annotation: `list[CollectedDataset]`.
- Return expressions: `[]; [_collected_dataset_from_rows(dataset_row, distributions_by_dataset_id.get(int(dataset_row['id']), [])) for dataset_row in dataset_rows]`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collected_distributions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.datasets._collected_dataset_from_rows`, `connection._fetchall`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/candidates.py`

<details>
<summary><code>save_repository_candidates</code> — Persist provider results under one search without overwriting duplicates.</summary>

- Source: [classification/candidates.py:23](../../backend/app/db/classification/candidates.py#L23).
- Arguments: `search_id: UUID, owner_id: str, candidates: list[RepositorySearchResult]`.
- Return annotation: `list[dict[str, object]]`.
- Return expressions: `[_repository_candidate_to_dict(row) for row in rows]`.
- Tables referenced directly or through resolved DB helpers: `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._repository_candidate_to_dict`, `classification.candidates._save_repository_candidates`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_save_repository_candidates</code> — Check search ownership and insert deduplicated candidate metadata.</summary>

- Source: [classification/candidates.py:42](../../backend/app/db/classification/candidates.py#L42).
- Arguments: `connection: AsyncConnection[DictRow], search_id: UUID, owner_id: str, candidates: list[RepositorySearchResult]`.
- Return annotation: `list[Row]`.
- Return expressions: `await _fetchall(connection, f'\n        SELECT {_CANDIDATE_COLUMNS}\n        FROM repository_candidates AS candidate\n        JOIN search_sessions AS session ON session.id = candidate.search_session_id\n        WHERE candidate.search_session_id = %s\n        ORDER BY candidate.created_at, candidate.id\n        ', (search_id,))`.
- Tables referenced directly or through resolved DB helpers: `repository_candidates`, `search_sessions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._normalized_keywords`, `classification.candidates._required_text`, `connection._fetchall`, `connection._fetchone`, `search.sessions._normalized_owner_id`, `serialization._jsonb`.
- Statically resolved callers: `app.db.classification.candidates.save_repository_candidates`, `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.search.jobs.complete_discovery`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_repository_candidate_to_dict</code> — Decode candidate metadata, classifications and stored timestamps.</summary>

- Source: [classification/candidates.py:112](../../backend/app/db/classification/candidates.py#L112).
- Arguments: `row: Row`.
- Return annotation: `dict[str, object]`.
- Return expressions: `{'id': UUID(str(row['id'])), 'search_session_id': UUID(str(row['search_session_id'])), 'search_query': str(row['search_query']), 'title': str(row['title']), 'description': str(row['description']), 'url': str(row['url']), 'source': str(row['source']), 'publisher': str(row['publisher']), 'publication_date': str(row['publication_date']), 'doi': str(row['doi']), 'keywords': [str(value) for value in _deserialize_json_array(row['keywords'], 'repository_candidates.keywords', 'keywords')], 'metadata': _deserialize_signals(row['metadata'], 'repository_candidates.metadata'), 'classification_status': str(row['classification_status']), 'classification_progress': row.get('classification_progress', {}), 'classification': None if classification is None else _deserialize_signals(classification, 'repository_candidates.classification'), 'error': str(row['error']), 'errors': row.get('errors', []), 'created_at': _format_timestamp(row['created_at']), 'updated_at': _format_timestamp(row['updated_at'])}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._deserialize_json_array`, `serialization._deserialize_signals`, `serialization._format_timestamp`.
- Statically resolved callers: `app.db.classification.candidates.save_repository_candidates`, `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.classification.candidates.claim_candidate_classification`, `app.db.classification.candidates._complete_candidate_classification`, `app.db.classification.candidates.fail_candidate_classification`, `app.db.search.progress.read_search_progress`, `tests.helpers.inspection.stored_candidate`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_required_text</code> — Trim required candidate text and reject blank values.</summary>

- Source: [classification/candidates.py:154](../../backend/app/db/classification/candidates.py#L154).
- Arguments: `value: str, label: str`.
- Return annotation: `str`.
- Return expressions: `normalized`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.candidates._save_repository_candidates`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_normalized_keywords</code> — Trim and deduplicate nonblank repository keywords.</summary>

- Source: [classification/candidates.py:161](../../backend/app/db/classification/candidates.py#L161).
- Arguments: `values: list[str]`.
- Return annotation: `list[str]`.
- Return expressions: `list(dict.fromkeys((value.strip() for value in values if value.strip())))`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.candidates._save_repository_candidates`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/completion.py`

<details>
<summary><code>complete_candidate_classification</code> — No accepted decision commits without a saved result or associated job.</summary>

- Source: [classification/completion.py:25](../../backend/app/db/classification/completion.py#L25).
- Arguments: `candidate_id: UUID, owner_id: str, classification: RepositoryClassification, *, expected_updated_at: datetime \| None=None`.
- Return annotation: `CandidateClassificationCompletion \| None`.
- Return expressions: `CandidateClassificationCompletion(candidate, collection); None`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._complete_candidate_classification`, `collection.reservations._reserve_repository_candidate_collection_job`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: `app.workers.classification.worker.ClassificationWorker.execute`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/jobs.py`

<details>
<summary><code>claim_candidate_classification</code> — Internal worker claim; ownership comes from the persisted search session.</summary>

- Source: [classification/jobs.py:28](../../backend/app/db/classification/jobs.py#L28).
- Arguments: `*, claim_token: UUID \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `None; {**_repository_candidate_to_dict(row), 'owner_id': str(row['owner_id'])}; {**_repository_candidate_to_dict(row), 'owner_id': str(row['owner_id'])} if row else None`.
- Tables referenced directly or through resolved DB helpers: `application_ownership`, `repository_candidates`, `search_sessions`, `worker_claims`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._repository_candidate_to_dict`, `connection._fetchone`, `connection._require_database_pool`, `execution.worker_claims.read_worker_claim`, `execution.worker_claims.record_worker_claim`, `schema._require_current_schema`.
- Statically resolved callers: `app.workers.classification.worker.ClassificationWorker.claim`, `tests.test_worker_claims.enqueue`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_complete_candidate_classification</code> — Persist a decision within the transaction that also reserves its collection.</summary>

- Source: [classification/jobs.py:79](../../backend/app/db/classification/jobs.py#L79).
- Arguments: `connection: AsyncConnection[DictRow], candidate_id: UUID, owner_id: str, classification: RepositoryClassification, *, expected_updated_at: datetime \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `None; _repository_candidate_to_dict(row)`.
- Tables referenced directly or through resolved DB helpers: `repository_candidates`, `search_sessions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._repository_candidate_to_dict`, `connection._fetchone`, `search.sessions._normalized_owner_id`, `serialization._jsonb`.
- Statically resolved callers: `app.db.classification.completion.complete_candidate_classification`, `tests.test_collection_workflow.test_claims_are_unique_and_ignore_uncommitted_jobs`, `tests.test_database._accept_repository_candidate`, `tests.test_search_progress.test_saved_dataset_without_job_and_missing_legacy_followup`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>fail_candidate_classification</code> — Record an operational classifier failure without treating it as rejection.</summary>

- Source: [classification/jobs.py:121](../../backend/app/db/classification/jobs.py#L121).
- Arguments: `candidate_id: UUID, owner_id: str, error: str, *, errors: list[dict] \| None=None, expected_updated_at: datetime \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `None; _repository_candidate_to_dict(row)`.
- Tables referenced directly or through resolved DB helpers: `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._repository_candidate_to_dict`, `connection._fetchone`, `connection._require_database_pool`, `schema._require_current_schema`, `search.sessions._normalized_owner_id`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.classification.worker.ClassificationWorker._fail`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_interrupted_candidate_classifications_error</code> — Make classifications interrupted by process restart explicitly retryable.</summary>

- Source: [classification/jobs.py:163](../../backend/app/db/classification/jobs.py#L163).
- Arguments: ``.
- Return annotation: `int`.
- Return expressions: `len(rows)`.
- Tables referenced directly or through resolved DB helpers: `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`, `connection._require_database_pool`, `schema._require_current_schema`, `serialization._jsonb`.
- Statically resolved callers: `app.lifecycle.lifespan`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/voting/history.py`

<details>
<summary><code>read_candidate_vote_history</code> — Read bounded vote attempts after verifying ownership of the candidate.</summary>

- Source: [classification/voting/history.py:11](../../backend/app/db/classification/voting/history.py#L11).
- Arguments: `candidate_id, owner_id, *, limit=100, offset=0`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `None; await _read_vote_history('repository_candidate_id', candidate_id, limit=limit, offset=offset)`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes._read_vote_history`, `connection._fetchone`, `connection._require_database_pool`, `search.sessions._normalized_owner_id`.
- Statically resolved callers: `app.api.routes.diagnostics.get_search_diagnostics`, `tests.test_vote_persistence.test_retry_only_failed_model_preserves_negative_votes`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>read_collection_vote_history</code> — Read owned collection votes across their shared retry lineage.</summary>

- Source: [classification/voting/history.py:27](../../backend/app/db/classification/voting/history.py#L27).
- Arguments: `job_id, owner_id, *, limit=100, offset=0`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `None; await _read_vote_history('collection_job_id', root['id'], limit=limit, offset=offset)`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`, `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes._read_vote_history`, `collection.jobs.get_collection_job_for_owner`, `connection._fetchone`, `connection._require_database_pool`.
- Statically resolved callers: `app.db.collection.traces.read_collection_trace`, `tests.test_backend_persistence_review.test_trace_pages_and_vote_history_do_not_export_raw_provider_errors`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_read_vote_history</code> — Read a bounded history page for a validated candidate or collection column.</summary>

- Source: [classification/voting/history.py:43](../../backend/app/db/classification/voting/history.py#L43).
- Arguments: `column, scope_id, *, limit=100, offset=0`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `{'attempts': [PublicVoteAttempt.from_row(row).to_dict() for row in reversed(rows[:page.limit])], **page.metadata(len(rows) > page.limit)}`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`, `connection._require_database_pool`, `public_history.PublicVoteAttempt.from_row`.
- Statically resolved callers: `app.db.classification.votes.read_candidate_vote_history`, `app.db.classification.votes.read_collection_vote_history`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/voting/runs.py`

<details>
<summary><code>prepare_vote_run</code> — Create or reuse a scoped run and publish its initial vote progress atomically.</summary>

- Source: [classification/voting/runs.py:14](../../backend/app/db/classification/voting/runs.py#L14).
- Arguments: `snapshot, *, candidate_id=None, job_id=None, expected_updated_at=None`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `run['id']`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_votes`, `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes._publish_progress`, `classification.votes._scope`, `connection._fetchone`, `connection._require_database_pool`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.stores.PostgresVoteStore.run`, `tests.test_backend_persistence_review.test_trace_pages_and_vote_history_do_not_export_raw_provider_errors`, `tests.test_backend_persistence_review.test_vote_history_retention_preserves_current_vote_cache`, `tests.test_llm_recovery.test_stale_worker_and_conflicting_vote_writes_are_rejected`, `tests.test_llm_recovery.test_reinitialization_preserves_votes_and_retry_counters`, `tests.test_vote_persistence.test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup`, `tests.test_worker_persistence.test_vote_progress_and_polling_preserve_completion_claim`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/voting/state.py`

<details>
<summary><code>_scope</code> — Lock the active parent version and resolve its reusable collection vote lineage.</summary>

- Source: [classification/voting/state.py:10](../../backend/app/db/classification/voting/state.py#L10).
- Arguments: `connection, candidate_id, job_id, version`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `scope`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.classification.votes.prepare_vote_run`, `app.db.classification.votes.claim_vote`, `app.db.classification.votes.finish_vote`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_lock_run</code> — Lock the vote run after its parent; callers keep the same connection and transaction.</summary>

- Source: [classification/voting/state.py:35](../../backend/app/db/classification/voting/state.py#L35).
- Arguments: `connection, run_id`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.votes.claim_vote`, `app.db.classification.votes.finish_vote`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_publish_progress</code> — Update stored vote counts without changing the parent claim version.</summary>

- Source: [classification/voting/state.py:43](../../backend/app/db/classification/voting/state.py#L43).
- Arguments: `connection, run_id, candidate_id, job_id`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `classification_votes`, `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `serialization._jsonb`.
- Statically resolved callers: `app.db.classification.votes.prepare_vote_run`, `app.db.classification.votes.claim_vote`, `app.db.classification.votes.finish_vote`, `app.db.classification.votes.mark_interrupted_votes_error`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `classification/voting/votes.py`

<details>
<summary><code>claim_vote</code> — Claim under the parent version; replaying the same token recovers the current vote.</summary>

- Source: [classification/voting/votes.py:17](../../backend/app/db/classification/voting/votes.py#L17).
- Arguments: `run_id, voter_id, *, candidate_id=None, job_id=None, expected_updated_at=None, token=None`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `vote`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`, `classification_votes`, `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes._check_vote_retry`, `classification.votes._lock_run`, `classification.votes._publish_progress`, `classification.votes._scope`, `connection._fetchone`, `connection._require_database_pool`.
- Statically resolved callers: `app.workers.stores.PostgresVoteStore.run`, `tests.test_backend_persistence_review.test_trace_pages_and_vote_history_do_not_export_raw_provider_errors`, `tests.test_backend_persistence_review.test_vote_history_retention_preserves_current_vote_cache`, `tests.test_llm_recovery.test_stale_worker_and_conflicting_vote_writes_are_rejected`, `tests.test_llm_recovery.test_reinitialization_preserves_votes_and_retry_counters`, `tests.test_vote_persistence.test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup`, `tests.test_worker_persistence.test_vote_progress_and_polling_preserve_completion_claim`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_check_vote_retry</code> — Enforce retry windows, provider due dates and per-code attempt budgets.</summary>

- Source: [classification/voting/votes.py:85](../../backend/app/db/classification/voting/votes.py#L85).
- Arguments: `scope, vote`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.votes.claim_vote`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>finish_vote</code> — Save the vote, attempt history and parent progress in one fenced transaction.</summary>

- Source: [classification/voting/votes.py:127](../../backend/app/db/classification/voting/votes.py#L127).
- Arguments: `run_id, voter_id, token, *, response=None, error='', errors=None, candidate_id=None, job_id=None, expected_updated_at=None`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`, `classification_votes`, `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes._lock_run`, `classification.votes._publish_progress`, `classification.votes._scope`, `connection._fetchone`, `connection._require_database_pool`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.stores.PostgresVoteStore.run`, `tests.test_backend_persistence_review.test_trace_pages_and_vote_history_do_not_export_raw_provider_errors`, `tests.test_backend_persistence_review.test_vote_history_retention_preserves_current_vote_cache`, `tests.test_llm_recovery.test_stale_worker_and_conflicting_vote_writes_are_rejected`, `tests.test_llm_recovery.test_reinitialization_preserves_votes_and_retry_counters`, `tests.test_vote_persistence.test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup`, `tests.test_worker_persistence.test_vote_progress_and_polling_preserve_completion_claim`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_interrupted_votes_error</code> — Startup recovery under the application's existing single-process policy.</summary>

- Source: [classification/voting/votes.py:194](../../backend/app/db/classification/voting/votes.py#L194).
- Arguments: ``.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`, `classification_votes`, `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes._publish_progress`, `connection._fetchall`, `connection._require_database_pool`, `serialization._jsonb`.
- Statically resolved callers: `app.lifecycle.lifespan`, `tests.test_llm_recovery.test_automatic_retry_preserves_successes_and_survives_restart`, `tests.test_vote_persistence.test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/completion.py`

<details>
<summary><code>complete_collection_job</code> — Save all collected datasets and mark their running job done atomically.</summary>

- Source: [collection/completion.py:22](../../backend/app/db/collection/completion.py#L22).
- Arguments: `job_id: int, collection_result: CollectionResult, *, expected_updated_at: datetime \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `None; completed_job`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collected_distributions`, `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `catalog.datasets._save_collected_dataset`, `collection.jobs._job_dataset_ids`, `collection.jobs._lock_running_collection_job`, `collection.jobs._mark_collection_job_done`, `connection._fetchall`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: `app.workers.collection.worker.CollectionWorker.execute`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_collection_job_done</code> — Save only job state and report fields; this operation does not store datasets.</summary>

- Source: [collection/completion.py:96](../../backend/app/db/collection/completion.py#L96).
- Arguments: `job_id: int, saved_count: int, report: CollectionReport \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `await _mark_collection_job_done(connection, job_id, saved_count, report)`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._mark_collection_job_done`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_mark_collection_job_done</code> — Update a running job report and outcome on the caller connection.</summary>

- Source: [collection/completion.py:108](../../backend/app/db/collection/completion.py#L108).
- Arguments: `connection: AsyncConnection[DictRow], job_id: int, saved_count: int, report: CollectionReport`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `_collection_job_to_dict(row) if row else None`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_done_message`, `collection.jobs._collection_job_to_dict`, `collection.traces.safe_observation`, `connection._fetchone`, `serialization._jsonb`, `serialization._serialize_discovery_methods`.
- Statically resolved callers: `app.db.collection.completion.complete_collection_job`, `app.db.collection.jobs.mark_collection_job_done`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_collection_job_done_message</code> — Choose the existing completion message from saved counts and report evidence.</summary>

- Source: [collection/completion.py:166](../../backend/app/db/collection/completion.py#L166).
- Arguments: `saved_count: int, report: CollectionReport`.
- Return annotation: `str`.
- Return expressions: `'No candidate URL was discovered.'; 'No health dataset with a valid file was found.'; 'No page was analyzed.'; f'Collection incomplete; {saved_count} dataset(s) saved.'; f'{saved_count} dataset(s) saved.'`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.collection.jobs._mark_collection_job_done`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/job_reads.py`

<details>
<summary><code>get_collection_job</code> — Read an internal job using the same representation as lifecycle writes.</summary>

- Source: [collection/job_reads.py:17](../../backend/app/db/collection/job_reads.py#L17).
- Arguments: `job_id: int`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `_collection_job_to_dict(row) if row else None`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `collection.jobs._get_collection_job_row`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>get_collection_job_for_owner</code> — Read only jobs explicitly associated with one of the owner's candidates.</summary>

- Source: [collection/job_reads.py:26](../../backend/app/db/collection/job_reads.py#L26).
- Arguments: `job_id: int, owner_id: str`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `None; job`.
- Tables referenced directly or through resolved DB helpers: `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `collection.jobs._job_dataset_ids`, `connection._fetchone`, `connection._require_database_pool`, `schema._require_current_schema`, `search.sessions._normalized_owner_id`.
- Statically resolved callers: `app.db.classification.votes.read_collection_vote_history`, `app.db.collection.traces.read_collection_trace`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_get_collection_job_row</code> — Read the stored fields required to reconstruct one collection job.</summary>

- Source: [collection/job_reads.py:51](../../backend/app/db/collection/job_reads.py#L51).
- Arguments: `connection, job_id: int`.
- Return annotation: `Row \| None`.
- Return expressions: `await _fetchone(connection, '\n        SELECT id, source_url, kind, repository_candidate_id,\n               status, saved_count, discovered_count,\n               analyzed_count, accepted_count, rejected_count,\n               invalid_distribution_count, discovery_methods, classification_progress,\n               message, error, errors, outcome, collection_coverage, collection_method_summary,\n               created_at, updated_at, finished_at, collection_deadline_at\n        FROM collection_jobs\n        WHERE id = %s\n        ', (job_id,))`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.collection.jobs.get_collection_job`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_job_dataset_ids</code> — Resolve unique dataset IDs associated with a collection job.</summary>

- Source: [collection/job_reads.py:68](../../backend/app/db/collection/job_reads.py#L68).
- Arguments: `connection, job_id: int`.
- Return annotation: `list[int]`.
- Return expressions: `[int(row['dataset_id']) for row in rows]`.
- Tables referenced directly or through resolved DB helpers: `dataset_discovery_observations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`.
- Statically resolved callers: `app.db.collection.completion.complete_collection_job`, `app.db.collection.jobs.get_collection_job_for_owner`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_collection_job_to_dict</code> — Decode the shared persisted-job representation for reads and writes.</summary>

- Source: [collection/job_reads.py:78](../../backend/app/db/collection/job_reads.py#L78).
- Arguments: `row: Row`.
- Return annotation: `dict[str, object]`.
- Return expressions: `{'id': int(row['id']), 'source_url': str(row['source_url']), 'kind': str(row['kind']), 'repository_candidate_id': UUID(str(row['repository_candidate_id'])) if row['repository_candidate_id'] is not None else None, 'status': str(row['status']), 'coverage': row.get('collection_coverage', {}), 'method_attempts': row.get('collection_method_summary', []), 'classification_progress': row.get('classification_progress', {}), 'saved_count': int(row['saved_count']), 'discovered_count': int(row['discovered_count']), 'analyzed_count': int(row['analyzed_count']), 'accepted_count': int(row['accepted_count']), 'rejected_count': int(row['rejected_count']), 'invalid_distribution_count': int(row['invalid_distribution_count']), 'discovery_methods': _deserialize_discovery_methods(row['discovery_methods']), 'message': str(row['message']), 'error': str(row['error']), 'errors': row.get('errors', []), 'outcome': row.get('outcome'), 'created_at': _format_timestamp(row['created_at']), 'updated_at': _format_timestamp(row['updated_at']), 'finished_at': _format_optional_timestamp(row['finished_at']), 'collection_deadline_at': _format_timestamp(row['collection_deadline_at']) if row.get('collection_deadline_at') is not None else None}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._deserialize_discovery_methods`, `serialization._format_optional_timestamp`, `serialization._format_timestamp`.
- Statically resolved callers: `app.db.collection.jobs.create_collection_job`, `app.db.collection.jobs.get_collection_job_for_owner`, `app.db.collection.jobs.claim_pending_collection_job`, `app.db.collection.jobs.get_collection_job`, `app.db.collection.jobs.mark_collection_job_running`, `app.db.collection.jobs._mark_collection_job_done`, `app.db.collection.jobs.mark_collection_job_error`, `app.db.collection.reservations._reserve_repository_candidate_collection_job`, `app.db.search.progress.read_search_progress`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/jobs.py`

<details>
<summary><code>create_collection_job</code> — Create a pending source job without executing collection work.</summary>

- Source: [collection/jobs.py:23](../../backend/app/db/collection/jobs.py#L23).
- Arguments: `source_url: str`.
- Return annotation: `dict[str, object]`.
- Return expressions: `_collection_job_to_dict(row)`.
- Tables referenced directly or through resolved DB helpers: `collection_job_candidates`, `collection_jobs`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `collection.jobs._insert_collection_job`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_interrupted_collection_jobs_error</code> — Fail interrupted running jobs; pending jobs remain available to the worker.</summary>

- Source: [collection/jobs.py:35](../../backend/app/db/collection/jobs.py#L35).
- Arguments: ``.
- Return annotation: `int`.
- Return expressions: `len(rows)`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`, `collection_method_attempts`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`, `connection._require_database_pool`, `schema._require_current_schema`, `serialization._jsonb`.
- Statically resolved callers: `app.lifecycle.lifespan`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>claim_pending_collection_job</code> — Acquire or recover the same job after an ambiguous database commit.</summary>

- Source: [collection/jobs.py:74](../../backend/app/db/collection/jobs.py#L74).
- Arguments: `*, claim_token: UUID \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `_collection_job_to_dict(row) if row else None`.
- Tables referenced directly or through resolved DB helpers: `application_ownership`, `collection_jobs`, `worker_claims`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `connection._fetchone`, `connection._require_database_pool`, `execution.worker_claims.read_worker_claim`, `execution.worker_claims.record_worker_claim`, `schema._require_current_schema`.
- Statically resolved callers: `app.workers.collection.worker.CollectionWorker.claim`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_insert_collection_job</code> — Create a pending job, preserving failed-job vote lineage when applicable.</summary>

- Source: [collection/jobs.py:123](../../backend/app/db/collection/jobs.py#L123).
- Arguments: `connection: AsyncConnection[DictRow], source_url: str, *, kind: str='source', repository_candidate_id: UUID \| None=None`.
- Return annotation: `Row \| None`.
- Return expressions: `await _fetchone(connection, "\n        INSERT INTO collection_jobs (\n            source_url, kind, repository_candidate_id, classification_root_id, status, message\n        )\n        VALUES (%s, %s, %s, %s, 'pending', 'Collection pending.')\n        RETURNING id, source_url, kind, repository_candidate_id,\n                  status, saved_count, discovered_count,\n                  analyzed_count, accepted_count, rejected_count,\n                  invalid_distribution_count, discovery_methods, classification_progress,\n                  message,\n                  error, errors, outcome, created_at, updated_at, finished_at,\n                  collection_deadline_at, collection_coverage, collection_method_summary\n        ", (source_url, kind, repository_candidate_id, root_id))`.
- Tables referenced directly or through resolved DB helpers: `collection_job_candidates`, `collection_jobs`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.collection.jobs.create_collection_job`, `app.db.collection.reservations._reserve_repository_candidate_collection_job`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_collection_job_running</code> — Start a pending job and initialize its collection deadline and progress fields.</summary>

- Source: [collection/jobs.py:164](../../backend/app/db/collection/jobs.py#L164).
- Arguments: `job_id: int`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `_collection_job_to_dict(row) if row else None`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `connection._fetchone`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_collection_job_error</code> — Fail a pending or running job without overwriting a superseding claim.</summary>

- Source: [collection/jobs.py:203](../../backend/app/db/collection/jobs.py#L203).
- Arguments: `job_id: int, error: str, *, errors: list[dict] \| None=None, expected_updated_at: datetime \| None=None`.
- Return annotation: `dict[str, object] \| None`.
- Return expressions: `_collection_job_to_dict(row) if row else None`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `connection._fetchone`, `connection._require_database_pool`, `schema._require_current_schema`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.collection.worker.CollectionWorker._fail`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_lock_running_collection_job</code> — Lock the running collection row and return its authoritative URL and version.</summary>

- Source: [collection/jobs.py:244](../../backend/app/db/collection/jobs.py#L244).
- Arguments: `connection: AsyncConnection[DictRow], job_id: int`.
- Return annotation: `Row \| None`.
- Return expressions: `await _fetchone(connection, "\n        SELECT id, source_url, updated_at\n        FROM collection_jobs\n        WHERE id = %s AND status = 'running'\n        FOR UPDATE\n        ", (job_id,))`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.collection.completion.complete_collection_job`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/reservations.py`

<details>
<summary><code>reserve_repository_candidate_collection_job</code> — Reserve follow-up explicitly; progress reads must never create work.</summary>

- Source: [collection/reservations.py:33](../../backend/app/db/collection/reservations.py#L33).
- Arguments: `candidate_id: UUID, owner_id: str`.
- Return annotation: `CollectionJobReservation`.
- Return expressions: `await _reserve_repository_candidate_collection_job(connection, candidate_id, owner_id)`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.reservations._reserve_repository_candidate_collection_job`, `connection._require_database_pool`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_reserve_repository_candidate_collection_job</code> — Reserve on the caller's transaction, including candidate associations.</summary>

- Source: [collection/reservations.py:49](../../backend/app/db/collection/reservations.py#L49).
- Arguments: `connection: AsyncConnection[DictRow], candidate_id: UUID, owner_id: str`.
- Return annotation: `CollectionJobReservation`.
- Return expressions: `CollectionJobReservation(job=None, created=False, already_collected=True, dataset_ids=tuple(await _existing_dataset_ids(connection, source_url))); CollectionJobReservation(job=_collection_job_to_dict(new_job), created=True, already_collected=False); CollectionJobReservation(job=_collection_job_to_dict(reservation_state), created=False, already_collected=False)`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.jobs._collection_job_to_dict`, `collection.jobs._insert_collection_job`, `collection.reservations._associate_job_candidate`, `collection.reservations._existing_dataset_ids`, `connection._fetchone`, `search.sessions._normalized_owner_id`.
- Statically resolved callers: `app.db.classification.completion.complete_candidate_classification`, `app.db.collection.reservations.reserve_repository_candidate_collection_job`, `tests.test_collection_workflow.test_claims_are_unique_and_ignore_uncommitted_jobs`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_associate_job_candidate</code> — Attach the candidate once using the caller's current transaction.</summary>

- Source: [collection/reservations.py:171](../../backend/app/db/collection/reservations.py#L171).
- Arguments: `connection: AsyncConnection[DictRow], job_id: int, candidate_id: UUID`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `collection_job_candidates`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.collection.reservations._reserve_repository_candidate_collection_job`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_existing_dataset_ids</code> — Resolve saved results by record URL or by its discovery observations.</summary>

- Source: [collection/reservations.py:184](../../backend/app/db/collection/reservations.py#L184).
- Arguments: `connection: AsyncConnection[DictRow], source_url: str`.
- Return annotation: `list[int]`.
- Return expressions: `[int(row['id']) for row in rows]`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `dataset_discovery_observations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`.
- Statically resolved callers: `app.db.collection.reservations._reserve_repository_candidate_collection_job`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/traces/reading.py`

<details>
<summary><code>read_collection_trace</code> — Read an owned trace with bounded paging and filter stored evidence for publication.</summary>

- Source: [collection/traces/reading.py:22](../../backend/app/db/collection/traces/reading.py#L22).
- Arguments: `job_id, owner_id, *, limit=100, offset=0`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `None; {'job_id': job_id, **page.metadata(truncated), 'checks_truncated': len(checks) > MAX_CHECKS_PER_PAGE or any((count > MAX_CHECKS_PER_METHOD for count in totals.values())), 'classification_history': await read_collection_vote_history(job_id, owner_id), 'coverage': safe_coverage(job.get('coverage', {})), 'method_attempts': [{'id': str(r['id']), 'retry_cycle': r['retry_cycle'], 'sequence': r['sequence'], **safe_observation(r['observation']), 'checks': by_method[r['id']]} for r in rows]}`.
- Tables referenced directly or through resolved DB helpers: `classification_runs`, `classification_vote_attempts`, `collection_job_candidates`, `collection_jobs`, `collection_method_attempts`, `collection_resource_checks`, `dataset_discovery_observations`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.votes.read_collection_vote_history`, `collection.jobs.get_collection_job_for_owner`, `collection.traces.safe_check`, `collection.traces.safe_coverage`, `collection.traces.safe_observation`, `collection.traces.safe_resource_key`, `connection._fetchall`, `connection._require_database_pool`.
- Statically resolved callers: `app.api.routes.diagnostics.get_search_diagnostics`, `tests.test_backend_persistence_review.test_trace_pages_and_vote_history_do_not_export_raw_provider_errors`, `tests.test_backend_persistence_review.test_legacy_trace_fields_are_filtered_again_on_read`, `tests.test_collection_traces.test_reinitialization_preserves_completed_job`, `tests.test_collection_traces.test_ipv6_diagnostic_urls_survive_storage_and_repeated_sanitization`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/traces/sanitization.py`

<details>
<summary><code>safe_url</code> — Keep a bounded public HTTP URL, removing credentials and sensitive query values.</summary>

- Source: [collection/traces/sanitization.py:16](../../backend/app/db/collection/traces/sanitization.py#L16).
- Arguments: `value`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `''; public_url(value)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.collection.traces.safe_resource_key`, `app.db.collection.traces.safe_check`, `app.db.collection.traces.safe_observation`, `tests.test_collection_traces.test_ipv6_diagnostic_urls_survive_storage_and_repeated_sanitization`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>safe_resource_key</code> — Retain a public resource label or a stable digest for an unpublishable filename.</summary>

- Source: [collection/traces/sanitization.py:28](../../backend/app/db/collection/traces/sanitization.py#L28).
- Arguments: `value`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `'resource:' + sha256(value.encode()).hexdigest(); label; safe_url(value)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.traces.safe_url`, `public_history.public_label`.
- Statically resolved callers: `app.db.collection.traces.write_collection_trace`, `app.db.collection.traces.read_collection_trace`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>safe_coverage</code> — Keep only recognized coverage fields and bounded integer counters.</summary>

- Source: [collection/traces/sanitization.py:39](../../backend/app/db/collection/traces/sanitization.py#L39).
- Arguments: `value`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `clean; {}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.api.presenters.collection.build_collection_job_view`, `app.db.collection.traces.read_collection_trace`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>safe_check</code> — Expose recognized access evidence and controlled diagnostic codes only.</summary>

- Source: [collection/traces/sanitization.py:57](../../backend/app/db/collection/traces/sanitization.py#L57).
- Arguments: `value`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `clean; {}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.traces.safe_url`, `public_history.bounded_diagnostics`, `public_history.public_label`.
- Statically resolved callers: `app.db.collection.traces.write_collection_trace`, `app.db.collection.traces.read_collection_trace`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>safe_observation</code> — Filter method observations and reconstruct messages from controlled diagnostic codes.</summary>

- Source: [collection/traces/sanitization.py:83](../../backend/app/db/collection/traces/sanitization.py#L83).
- Arguments: `observation`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `clean; {}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.traces.safe_url`, `public_history.bounded_diagnostics`, `public_history.public_label`, `public_history.public_timestamp`.
- Statically resolved callers: `app.api.presenters.collection.build_collection_job_view`, `app.db.collection.jobs._mark_collection_job_done`, `app.db.collection.traces.write_collection_trace`, `app.db.collection.traces.read_collection_trace`, `tests.test_collection_failure_details.test_metadata_request_count_is_sanitized`, `tests.test_collection_failure_details.test_trace_rebuilds_reason_and_rejects_uncontrolled_phase`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `collection/traces/writing.py`

<details>
<summary><code>write_collection_trace</code> — Record bounded observations only while the collection claim is still current.</summary>

- Source: [collection/traces/writing.py:17](../../backend/app/db/collection/traces/writing.py#L17).
- Arguments: `job_id, claim_version, sequence, observation`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `False; True`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`, `collection_method_attempts`, `collection_resource_checks`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `collection.traces.safe_check`, `collection.traces.safe_observation`, `collection.traces.safe_resource_key`, `connection._fetchone`, `connection._require_database_pool`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.stores.PostgresCollectionTraceWriter.__call__`, `tests.test_backend_persistence_review.test_trace_pages_and_vote_history_do_not_export_raw_provider_errors`, `tests.test_backend_persistence_review.test_legacy_trace_fields_are_filtered_again_on_read`, `tests.test_backend_persistence_review.test_maintenance_dry_run_preserves_receipts_and_protects_active_history`, `tests.test_backend_persistence_review.test_maintenance_apply_only_deletes_selected_terminal_history`, `tests.test_collection_traces.test_ipv6_diagnostic_urls_survive_storage_and_repeated_sanitization`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `connection.py`

<details>
<summary><code>check_database_readiness</code> — Probe the initialized pool within one acquisition/query time budget.</summary>

- Source: [connection.py:20](../../backend/app/db/connection.py#L20).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_initialized`, `connection._require_database_pool`.
- Statically resolved callers: `app.main.ready`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_database_url_from_env</code> — Require the configured PostgreSQL connection URL.</summary>

- Source: [connection.py:46](../../backend/app/db/connection.py#L46).
- Arguments: ``.
- Return annotation: `str`.
- Return expressions: `database_url`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.connection.open_database_pool`, `app.db.execution.application_lock.application_lock`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>configured_database_timeouts</code> — Bound ordinary SQL; migrations and maintenance set local overrides.</summary>

- Source: [connection.py:56](../../backend/app/db/connection.py#L56).
- Arguments: ``.
- Return annotation: `tuple[int, int]`.
- Return expressions: `(statement_timeout, lock_timeout)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.connection.open_database_pool`, `app.lifecycle.lifespan`, `tests.test_database_timeouts.test_invalid_database_timeouts_fail_configuration`, `tests.test_database_timeouts.test_database_timeout_defaults_and_lock_order`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>open_database_pool</code> — Configure and open the shared autocommit pool with bounded SQL timeouts.</summary>

- Source: [connection.py:78](../../backend/app/db/connection.py#L78).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._database_url_from_env`, `connection._set_initialized_pool`, `connection.configured_database_timeouts`.
- Statically resolved callers: `app.db.maintenance.main.run`, `app.lifecycle.lifespan`, `app.migrate.run_migrations`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>open_database_pool.configure</code> — Configure statement and lock timeouts for a new pooled connection.</summary>

- Source: [connection.py:86](../../backend/app/db/connection.py#L86).
- Arguments: `connection`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>close_database_pool</code> — Invalidate initialization state and close the shared pool.</summary>

- Source: [connection.py:106](../../backend/app/db/connection.py#L106).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._set_initialized_pool`.
- Statically resolved callers: `app.db.maintenance.main.run`, `app.lifecycle.lifespan`, `app.migrate.run_migrations`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_set_initialized_pool</code> — Record which pool has passed schema initialization.</summary>

- Source: [connection.py:117](../../backend/app/db/connection.py#L117).
- Arguments: `pool: AsyncConnectionPool[DictRow] \| None`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.connection.open_database_pool`, `app.db.connection.close_database_pool`, `app.db.schema.init_database`, `app.db.schema.validate_database_schema`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_require_database_initialized</code> — Reject runtime operations on a pool that has not passed schema initialization.</summary>

- Source: [connection.py:122](../../backend/app/db/connection.py#L122).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`.
- Statically resolved callers: `app.db.connection.check_database_readiness`, `app.db.schema._require_current_schema`, `tests.helpers.inspection.stored_datasets`, `tests.helpers.inspection.stored_candidate`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_require_database_pool</code> — Return the current pool or reject access before startup.</summary>

- Source: [connection.py:127](../../backend/app/db/connection.py#L127).
- Arguments: ``.
- Return annotation: `AsyncConnectionPool[DictRow]`.
- Return expressions: `_database_pool`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.datasets.save_collected_datasets`, `app.db.catalog.datasets.get_collected_datasets`, `app.db.catalog.observations.list_dataset_discovery_observations`, `app.db.catalog.search.search_collected_datasets`, `app.db.classification.candidates.save_repository_candidates`, `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.classification.candidates.claim_candidate_classification`, `app.db.classification.candidates.fail_candidate_classification`, `app.db.classification.candidates.mark_interrupted_candidate_classifications_error`, `app.db.classification.completion.complete_candidate_classification`, `app.db.classification.votes.prepare_vote_run`, `app.db.classification.votes.claim_vote`, `app.db.classification.votes.finish_vote`, `app.db.classification.votes.read_candidate_vote_history`, `app.db.classification.votes.read_collection_vote_history`, `app.db.classification.votes._read_vote_history`, `app.db.classification.votes.mark_interrupted_votes_error`, `app.db.collection.completion.complete_collection_job`, `app.db.collection.jobs.create_collection_job`, `app.db.collection.jobs.get_collection_job_for_owner`, `app.db.collection.jobs.mark_interrupted_collection_jobs_error`, `app.db.collection.jobs.claim_pending_collection_job`, `app.db.collection.jobs.get_collection_job`, `app.db.collection.jobs.mark_collection_job_running`, `app.db.collection.jobs.mark_collection_job_done`, `app.db.collection.jobs.mark_collection_job_error`, `app.db.collection.reservations.reserve_repository_candidate_collection_job`, `app.db.collection.traces.write_collection_trace`, `app.db.collection.traces.read_collection_trace`, `app.db.connection.check_database_readiness`, `app.db.connection._require_database_initialized`, `app.db.execution.quotas.consume_api_quota`, `app.db.execution.quotas.consume_quota_limits`, `app.db.execution.retries.schedule_llm_retry`, `app.db.maintenance.maintain_database`, `app.db.schema.init_database`, `app.db.schema.validate_database_schema`, `app.db.search.jobs.admit_search`, `app.db.search.jobs.claim_search`, `app.db.search.jobs.reserve_external_search`, `app.db.search.jobs.complete_discovery`, `app.db.search.jobs.fail_discovery`, `app.db.search.progress.read_search_progress`, `app.db.search.sessions.create_search_session`, `app.db.search.sessions.complete_search_session`, `app.db.search.sessions.mark_interrupted_search_sessions_error`, `app.db.search.sessions.latest_search_id`, `tests.helpers.inspection.stored_datasets`, `tests.helpers.inspection.stored_candidate`, `tests.helpers.workflows.start_candidate`, `tests.helpers.workflows.rows`, `tests.test_application_lock.test_lock_connection_is_dedicated_and_does_not_exhaust_single_slot_pool`, `tests.test_application_lock.test_activation_is_runtime_only_and_idempotent`, `tests.test_application_lock.test_missing_or_inactive_generation_rejects_claim`, `tests.test_application_lock.test_activation_verifies_actual_lock_before_rotating_generation`, `tests.test_async_searches.test_local_ranked_results_and_legacy_completion_are_atomic`, `tests.test_backend_persistence_review.sql`, `tests.test_collection_budget.test_worker_keeps_slot_and_persists_partial_result_after_expiration`, `tests.test_collection_budget.test_expired_job_concludes_without_any_external_call`, `tests.test_collection_budget_persistence.sql`, `tests.test_collection_workflow.test_claims_are_unique_and_ignore_uncommitted_jobs`, `tests.test_connector_persistence.test_reinitialization_preserves_datasets_and_record_identity`, `tests.test_database._schema_version`, `tests.test_database._table_names`, `tests.test_database._fetchall`, `tests.test_database._execute`, `tests.test_database._insert_minimal_dataset`, `tests.test_database._accept_repository_candidate`, `tests.test_database.test_shared_job_reservation_serializes_two_owners_on_separate_connections`, `tests.test_database.test_table_exists_checks_current_schema_only`, `tests.test_database.test_init_database_rejects_current_version_with_missing_managed_tables`, `tests.test_database.test_reinitialization_preserves_searches_and_receipts`, `tests.test_database.test_schema_migration_rechecks_version_after_acquiring_lock`, `tests.test_database_timeouts.configured_pool`, `tests.test_llm_recovery.sql`, `tests.test_pipeline_outcomes_persistence.query`, `tests.test_public_quotas.rows`, `tests.test_public_quotas.test_daily_counter_resets_at_the_next_utc_day`, `tests.test_public_quotas.test_local_results_remain_available_when_external_budget_is_exhausted`, `tests.test_public_quotas.test_older_request_timestamp_never_moves_the_quota_window_backward`, `tests.test_readiness.test_real_database_initialization_exhaustion_and_recovery`, `tests.test_search_command_routes.test_concurrent_searches_share_atomic_queue_capacity`, `tests.test_search_progress.test_query_count_is_constant_and_snapshot_does_not_mix_commits`, `tests.test_search_progress.test_query_count_is_constant_and_snapshot_does_not_mix_commits.observed`, `tests.test_search_progress.test_saved_dataset_without_job_and_missing_legacy_followup`, `tests.test_search_progress.test_associated_job_and_dataset_ids_win_over_other_work_at_same_url`, `tests.test_standalone_api_failures.sql`, `tests.test_standalone_api_runtime.test_real_server_collects_without_client_then_restores_after_restart.persisted_result`, `tests.test_standalone_api_runtime.test_native_local_api_and_python_client_need_no_credentials`, `tests.test_validation_persistence.test_plain_errors_at_download_urls_stay_unconfirmed_in_saved_audit`, `tests.test_validation_persistence.test_validation_status_large_size_and_rejected_audit_are_persisted`, `tests.test_validation_persistence.test_access_diagnosis_survives_storage_and_public_conversion`, `tests.test_vote_persistence.test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup`, `tests.test_worker_claims.sql`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_fetchone</code> — Execute caller-supplied SQL and return one dictionary row or None.</summary>

- Source: [connection.py:136](../../backend/app/db/connection.py#L136).
- Arguments: `connection: AsyncConnection[DictRow], sql: str, parameters: QueryParameters=None`.
- Return annotation: `Row \| None`.
- Return expressions: `dict(row) if row is not None else None`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.datasets._upsert_collected_dataset`, `app.db.classification.candidates._save_repository_candidates`, `app.db.classification.candidates.claim_candidate_classification`, `app.db.classification.candidates._complete_candidate_classification`, `app.db.classification.candidates.fail_candidate_classification`, `app.db.classification.votes.prepare_vote_run`, `app.db.classification.votes.claim_vote`, `app.db.classification.votes.finish_vote`, `app.db.classification.votes._scope`, `app.db.classification.votes.read_candidate_vote_history`, `app.db.classification.votes.read_collection_vote_history`, `app.db.classification.votes._publish_progress`, `app.db.collection.jobs.get_collection_job_for_owner`, `app.db.collection.jobs.claim_pending_collection_job`, `app.db.collection.jobs._insert_collection_job`, `app.db.collection.jobs.mark_collection_job_running`, `app.db.collection.jobs._mark_collection_job_done`, `app.db.collection.jobs.mark_collection_job_error`, `app.db.collection.jobs._get_collection_job_row`, `app.db.collection.jobs._lock_running_collection_job`, `app.db.collection.reservations._reserve_repository_candidate_collection_job`, `app.db.collection.traces.write_collection_trace`, `app.db.connection.check_database_readiness`, `app.db.execution.application_lock.ApplicationOwnership._check_locked`, `app.db.execution.application_lock.fence_worker_claim`, `app.db.execution.application_lock.application_lock`, `app.db.execution.commands.read_command`, `app.db.execution.quotas.reserve_work`, `app.db.execution.quotas._consume_quota`, `app.db.execution.retries.schedule_llm_retry`, `app.db.execution.worker_claims.read_worker_claim`, `app.db.maintenance.maintain_database`, `app.db.schema._assert_current_schema_search_index_exists`, `app.db.schema._table_exists`, `app.db.schema._schema_version`, `app.db.search.jobs.admit_search`, `app.db.search.jobs.claim_search`, `app.db.search.jobs._lock_attempt`, `app.db.search.jobs.fail_discovery`, `app.db.search.progress.read_search_progress`, `app.db.search.sessions.create_search_session`, `app.db.search.sessions._complete_search_session`, `app.db.search.sessions.latest_search_id`, `tests.helpers.inspection.stored_candidate`, `tests.test_application_lock.test_activation_is_runtime_only_and_idempotent`, `tests.test_application_lock.test_activation_verifies_actual_lock_before_rotating_generation`, `tests.test_connector_persistence.test_reinitialization_preserves_datasets_and_record_identity`, `tests.test_database._insert_minimal_dataset`, `tests.test_database.test_table_exists_checks_current_schema_only`, `tests.test_database_timeouts.settings`, `tests.test_database_timeouts.test_migration_deadlines_are_local_and_runtime_generation_starts_empty`, `tests.test_database_timeouts.test_statement_deadline_rolls_back_and_connection_remains_reusable`, `tests.test_database_timeouts.test_row_lock_deadline_rolls_back_and_preserves_pool`, `tests.test_validation_persistence.test_plain_errors_at_download_urls_stay_unconfirmed_in_saved_audit`, `tests.test_validation_persistence.test_validation_status_large_size_and_rejected_audit_are_persisted`, `tests.test_validation_persistence.test_access_diagnosis_survives_storage_and_public_conversion`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_fetchall</code> — Execute caller-supplied SQL and return dictionary rows.</summary>

- Source: [connection.py:146](../../backend/app/db/connection.py#L146).
- Arguments: `connection: AsyncConnection[DictRow], sql: str, parameters: QueryParameters=None`.
- Return annotation: `list[Row]`.
- Return expressions: `[dict(row) for row in rows]`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.datasets.get_collected_datasets`, `app.db.catalog.datasets._datasets_with_distributions`, `app.db.catalog.distributions._fetch_collected_distribution_rows`, `app.db.catalog.observations._select_dataset_discovery_observations`, `app.db.catalog.search.search_collected_datasets`, `app.db.classification.candidates._save_repository_candidates`, `app.db.classification.candidates.mark_interrupted_candidate_classifications_error`, `app.db.classification.votes._read_vote_history`, `app.db.classification.votes.mark_interrupted_votes_error`, `app.db.collection.completion.complete_collection_job`, `app.db.collection.jobs._job_dataset_ids`, `app.db.collection.jobs.mark_interrupted_collection_jobs_error`, `app.db.collection.reservations._existing_dataset_ids`, `app.db.collection.traces.read_collection_trace`, `app.db.maintenance.maintain_database`, `app.db.schema._assert_current_schema_repository_persistence_exists`, `app.db.schema._assert_current_schema_has_no_obsolete_columns`, `app.db.search.progress.read_search_progress`, `app.db.search.sessions.mark_interrupted_search_sessions_error`, `tests.helpers.inspection.stored_datasets`, `tests.helpers.workflows.rows`, `tests.test_database._table_names`, `tests.test_database._fetchall`, `tests.test_pipeline_outcomes_persistence.query`, `tests.test_public_quotas.rows`, `tests.test_search_command_routes.test_concurrent_searches_share_atomic_queue_capacity`, `tests.test_search_progress.test_query_count_is_constant_and_snapshot_does_not_mix_commits`, `tests.test_standalone_api_failures.sql`, `tests.test_vote_persistence.test_parent_recovery_prevents_late_vote_claim_and_finish_before_vote_cleanup`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `execution/application_lock.py`

<details>
<summary><code>ApplicationOwnership.__init__</code> — Bind the ownership connection, lock key, probe bounds and health state.</summary>

- Source: [execution/application_lock.py:31](../../backend/app/db/execution/application_lock.py#L31).
- Arguments: `self, connection, key: int, *, probe_timeout: float=2.0`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>ApplicationOwnership.healthy</code> — Report whether the owning session is open and not marked lost.</summary>

- Source: [execution/application_lock.py:39](../../backend/app/db/execution/application_lock.py#L39).
- Arguments: `self`.
- Return annotation: `bool`.
- Return expressions: `not self.lost.is_set() and (not self.connection.closed)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>ApplicationOwnership.require_held</code> — Reject work after ownership loss.</summary>

- Source: [execution/application_lock.py:42](../../backend/app/db/execution/application_lock.py#L42).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>ApplicationOwnership._mark_lost</code> — Mark ownership lost and stop worker processing.</summary>

- Source: [execution/application_lock.py:47](../../backend/app/db/execution/application_lock.py#L47).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>ApplicationOwnership.check</code> — Check this session's actual lock; never reconnect or silently reacquire it.</summary>

- Source: [execution/application_lock.py:54](../../backend/app/db/execution/application_lock.py#L54).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>ApplicationOwnership.activate</code> — Fence previous workers before recovery, using the actual owning session.</summary>

- Source: [execution/application_lock.py:59](../../backend/app/db/execution/application_lock.py#L59).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: `application_ownership`.
- Ownership: opens connection: False; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>ApplicationOwnership._check_locked</code> — Verify the actual advisory lock within a bounded probe.</summary>

- Source: [execution/application_lock.py:75](../../backend/app/db/execution/application_lock.py#L75).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `pg_locks`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>require_application_ownership</code> — Require the current application ownership context to remain healthy.</summary>

- Source: [execution/application_lock.py:105](../../backend/app/db/execution/application_lock.py#L105).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.workers.runtime._consume`, `app.workers.sql_retries.persist_with_retry`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>fence_worker_claim</code> — Hold the generation row through the claim transaction and receipt replay.</summary>

- Source: [execution/application_lock.py:111](../../backend/app/db/execution/application_lock.py#L111).
- Arguments: `connection`.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: `application_ownership`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.execution.worker_claims.read_worker_claim`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>application_lock</code> — Hold one database/schema owner through startup, workers and pool shutdown.</summary>

- Source: [execution/application_lock.py:126](../../backend/app/db/execution/application_lock.py#L126).
- Arguments: `*, probe_interval: float=1.0, probe_timeout: float=2.0`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._database_url_from_env`, `connection._fetchone`.
- Statically resolved callers: `app.db.maintenance.maintain_database`, `app.lifecycle.lifespan`, `app.migrate.run_migrations`, `tests.test_application_lock.test_second_instance_cannot_run_recovery_or_migrations`, `tests.test_application_lock.test_released_lock_is_detected_and_never_reacquired`, `tests.test_application_lock.test_background_monitor_detects_loss_without_a_request_probe`, `tests.test_application_lock.test_cancelled_worker_does_not_release_application_lock`, `tests.test_application_lock.test_lock_connection_is_dedicated_and_does_not_exhaust_single_slot_pool`, `tests.test_application_lock.test_activation_is_runtime_only_and_idempotent`, `tests.test_application_lock.test_missing_or_inactive_generation_rejects_claim`, `tests.test_application_lock.test_activation_verifies_actual_lock_before_rotating_generation`, `tests.test_backend_persistence_review.test_maintenance_apply_refuses_live_api_ownership`, `tests.test_worker_claims.test_replacement_generation_rejects_old_claims_before_monitor_detects_loss`, `tests.test_worker_claims.test_replacement_waits_for_inflight_claim_commit_before_recovery`, `tests.test_worker_claims.test_replacement_waits_for_inflight_claim_commit_before_recovery.replace`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>application_lock.watch</code> — Monitor the actual ownership lock and close the owning session on loss.</summary>

- Source: [execution/application_lock.py:150](../../backend/app/db/execution/application_lock.py#L150).
- Arguments: ``.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `execution/commands.py`

<details>
<summary><code>validate_command_key</code> — Validate the syntax and maximum size of an idempotency key.</summary>

- Source: [execution/commands.py:17](../../backend/app/db/execution/commands.py#L17).
- Arguments: `key: str`.
- Return annotation: `str`.
- Return expressions: `key`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.execution.commands.read_command`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_fingerprint</code> — Hash the canonical command operation and payload with the existing version.</summary>

- Source: [execution/commands.py:25](../../backend/app/db/execution/commands.py#L25).
- Arguments: `operation: str, payload: dict`.
- Return annotation: `str`.
- Return expressions: `hashlib.sha256(json.dumps({'version': 1, 'operation': operation, 'payload': payload}, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.execution.commands.read_command`, `app.db.execution.commands.record_command`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>read_command</code> — Lock before quota/resource locks. A replay never reserves work again.</summary>

- Source: [execution/commands.py:36](../../backend/app/db/execution/commands.py#L36).
- Arguments: `connection, owner_id, key, operation, payload`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `row['result'] if row else None`.
- Tables referenced directly or through resolved DB helpers: `api_commands`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `execution.commands._fingerprint`, `execution.commands.validate_command_key`.
- Statically resolved callers: `app.db.search.jobs.admit_search`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>record_command</code> — Insert a command receipt on the caller transaction.</summary>

- Source: [execution/commands.py:51](../../backend/app/db/execution/commands.py#L51).
- Arguments: `connection, owner_id, key, operation, payload, result`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `api_commands`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `execution.commands._fingerprint`, `serialization._jsonb`.
- Statically resolved callers: `app.db.search.jobs.admit_search`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `execution/quotas.py`

<details>
<summary><code>consume_api_quota</code> — Consume one request from an owner's minute quota.</summary>

- Source: [execution/quotas.py:21](../../backend/app/db/execution/quotas.py#L21).
- Arguments: `owner_id: str, operation: str, *, limit: int`.
- Return annotation: `APIQuotaDecision`.
- Return expressions: `await _consume_quota(connection, QuotaLimit(owner_id, operation, limit), amount=1)`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`, `execution.quotas._consume_quota`, `schema._require_current_schema`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>consume_quota_limits</code> — Charge all request limits or none, before any external request is started.</summary>

- Source: [execution/quotas.py:29](../../backend/app/db/execution/quotas.py#L29).
- Arguments: `quotas: tuple[QuotaLimit, ...]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`, `execution.quotas.reserve_quota_limits`, `schema._require_current_schema`.
- Statically resolved callers: `app.auth.security.enforce_api_quota`, `app.auth.security.enforce_public_online_quota`, `app.auth.security.enforce_session_creation_quota`, `tests.test_public_quotas.test_daily_counter_resets_at_the_next_utc_day`, `tests.test_public_quotas.test_local_results_remain_available_when_external_budget_is_exhausted`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>reserve_quota_limits</code> — The caller must own a transaction; rejection must roll back its entire reservation.</summary>

- Source: [execution/quotas.py:43](../../backend/app/db/execution/quotas.py#L43).
- Arguments: `connection, quotas: tuple[QuotaLimit, ...], *, amount: int`.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `execution.quotas._consume_quota`.
- Statically resolved callers: `app.db.execution.quotas.consume_quota_limits`, `app.db.execution.quotas.reserve_work`, `app.db.search.jobs.admit_search`, `app.db.search.jobs.reserve_external_search`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>lock_work_admission</code> — Acquire the shared admission lock before candidate or job row locks.</summary>

- Source: [execution/quotas.py:57](../../backend/app/db/execution/quotas.py#L57).
- Arguments: `connection, admission: WorkAdmission \| None`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.search.jobs.complete_discovery`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>reserve_work</code> — Reserve one slot per candidate pipeline or explicit retry in the caller's transaction.</summary>

- Source: [execution/quotas.py:65](../../backend/app/db/execution/quotas.py#L65).
- Arguments: `connection, admission: WorkAdmission \| None, *, amount: int`.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`, `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `execution.quotas.reserve_quota_limits`.
- Statically resolved callers: `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.search.jobs.complete_discovery`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_consume_quota</code> — Atomically charge a fixed UTC quota window and return its admission decision.</summary>

- Source: [execution/quotas.py:83](../../backend/app/db/execution/quotas.py#L83).
- Arguments: `connection, quota: QuotaLimit, *, amount: int`.
- Return annotation: `APIQuotaDecision`.
- Return expressions: `APIQuotaDecision(bool(row['allowed']), int(row['request_count']), int(row['retry_after_seconds']))`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.execution.quotas.consume_api_quota`, `app.db.execution.quotas.reserve_quota_limits`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `execution/retries.py`

<details>
<summary><code>schedule_llm_retry</code> — Requeue the current candidate or collection job while retaining its capacity.</summary>

- Source: [execution/retries.py:13](../../backend/app/db/execution/retries.py#L13).
- Arguments: `item_id, version, diagnostics, *, collection=False`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `(False, diagnostics); (True, diagnostics)`.
- Tables referenced directly or through resolved DB helpers: `collection_jobs`, `repository_candidates`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_pool`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.classification.worker.ClassificationWorker._retry`, `app.workers.collection.worker.CollectionWorker._retry`, `tests.test_collection_budget_persistence.test_automatic_retry_starts_fresh_budget_only_when_claimed`, `tests.test_collection_budget_persistence.test_retry_due_can_fall_after_previous_attempt_deadline`, `tests.test_collection_budget_persistence.test_retry_after_is_not_shortened_by_previous_attempt_budget`, `tests.test_collection_budget_persistence.test_exhausted_attempt_cannot_gain_budget_by_scheduling_retry`, `tests.test_collection_budget_persistence.test_retry_limit_does_not_clear_current_attempt_deadline`, `tests.test_collection_budget_persistence.test_exhausted_llm_policy_adds_collection_diagnostic_only_after_expiration`, `tests.test_llm_recovery.test_stale_worker_and_conflicting_vote_writes_are_rejected`, `tests.test_worker_claims.test_automatic_retry_respects_due_date_and_fences_old_receipt`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `execution/worker_claims.py`

<details>
<summary><code>read_worker_claim</code> — Call inside a transaction, before taking any task row locks.</summary>

- Source: [execution/worker_claims.py:18](../../backend/app/db/execution/worker_claims.py#L18).
- Arguments: `connection: AsyncConnection[DictRow], token: UUID, queue: Queue`.
- Return annotation: `Row \| None`.
- Return expressions: `receipt`.
- Tables referenced directly or through resolved DB helpers: `application_ownership`, `worker_claims`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `execution.application_lock.fence_worker_claim`.
- Statically resolved callers: `app.db.classification.candidates.claim_candidate_classification`, `app.db.collection.jobs.claim_pending_collection_job`, `app.db.search.jobs.claim_search`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>record_worker_claim</code> — Commit the receipt and task transition together; empty polls need no receipt.</summary>

- Source: [execution/worker_claims.py:35](../../backend/app/db/execution/worker_claims.py#L35).
- Arguments: `connection: AsyncConnection[DictRow], token: UUID, queue: Queue, resource_id: object, claim_version: datetime`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `worker_claims`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.candidates.claim_candidate_classification`, `app.db.collection.jobs.claim_pending_collection_job`, `app.db.search.jobs.claim_search`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `maintenance.py`

<details>
<summary><code>RetentionPolicy.__post_init__</code> — Validate retention ranges and the explicit command replay retention window.</summary>

- Source: [maintenance.py:26](../../backend/app/db/maintenance.py#L26).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_retention_operations</code> — Return only fixed SQL identifiers; no SQL fragments originate in configuration.</summary>

- Source: [maintenance.py:61](../../backend/app/db/maintenance.py#L61).
- Arguments: `policy: RetentionPolicy`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `api_commands`, `classification_runs`, `collection_job_candidates`, `collection_jobs`, `repository_candidates`, `search_sessions`, `worker_claims`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.maintenance.maintain_database`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>maintain_database</code> — Report eligible rows; an explicit apply prunes bounded batches under exclusive ownership.</summary>

- Source: [maintenance.py:178](../../backend/app/db/maintenance.py#L178).
- Arguments: `policy: RetentionPolicy \| None=None, *, apply: bool=False, batch_size: int=1000`.
- Return annotation: `dict`.
- Return expressions: `report`.
- Tables referenced directly or through resolved DB helpers: `api_commands`, `classification_runs`, `collection_job_candidates`, `collection_jobs`, `information_schema.columns`, `information_schema.tables`, `pg_indexes`, `repository_candidates`, `schema_migrations`, `search_sessions`, `worker_claims`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`, `connection._fetchone`, `connection._require_database_pool`, `execution.application_lock.application_lock`, `maintenance._retention_operations`, `schema.validate_database_schema`.
- Statically resolved callers: `app.db.maintenance.main.run`, `tests.test_backend_persistence_review.test_maintenance_dry_run_preserves_receipts_and_protects_active_history`, `tests.test_backend_persistence_review.test_maintenance_apply_only_deletes_selected_terminal_history`, `tests.test_backend_persistence_review.test_maintenance_keeps_replay_targets_and_respects_explicit_window`, `tests.test_backend_persistence_review.test_maintenance_apply_refuses_live_api_ownership`, `tests.test_backend_persistence_review.test_vote_history_retention_preserves_current_vote_cache`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>main</code> — Run the explicit maintenance CLI with controlled error reporting.</summary>

- Source: [maintenance.py:250](../../backend/app/db/maintenance.py#L250).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `tests.test_backend_persistence_review.test_maintenance_cli_failure_does_not_print_connection_details`.
- Direct call sites in application-code files: False; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>main.run</code> — Open the maintenance pool, execute retention and close the pool.</summary>

- Source: [maintenance.py:265](../../backend/app/db/maintenance.py#L265).
- Arguments: ``.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `api_commands`, `classification_runs`, `collection_job_candidates`, `collection_jobs`, `information_schema.columns`, `information_schema.tables`, `pg_indexes`, `repository_candidates`, `schema_migrations`, `search_sessions`, `worker_claims`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection.close_database_pool`, `connection.open_database_pool`, `maintenance.maintain_database`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `migrations/__init__.py`

<details>
<summary><code>migration_for_version</code> — Select the registered migration or reject an unsupported version.</summary>

- Source: [migrations/__init__.py:12](../../backend/app/db/migrations/__init__.py#L12).
- Arguments: `version: int`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `MIGRATIONS[version]`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.schema._migration_for_version`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `migrations/v001.py`

<details>
<summary><code>_migrate_0_to_1</code> — Create the baseline; the migration runner owns validation and its transaction.</summary>

- Source: [migrations/v001.py:550](../../backend/app/db/migrations/v001.py#L550).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `api_commands`, `api_rate_limits`, `application_ownership`, `classification_runs`, `classification_vote_attempts`, `classification_votes`, `collected_datasets`, `collected_distributions`, `collection_job_candidates`, `collection_jobs`, `collection_method_attempts`, `collection_resource_checks`, `data_sources`, `dataset_discovery_observations`, `repository_candidates`, `search_local_results`, `search_sessions`, `worker_claims`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `owner_ids.py`

<details>
<summary><code>validate_owner_id</code> — Validate the stored owner ID without silently trimming or changing it.</summary>

- Source: [owner_ids.py:6](../../backend/app/db/owner_ids.py#L6).
- Arguments: `owner_id: str`.
- Return annotation: `str`.
- Return expressions: `normalized_owner_id`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.candidates._save_repository_candidates`, `app.db.classification.candidates._complete_candidate_classification`, `app.db.classification.candidates.fail_candidate_classification`, `app.db.classification.votes.read_candidate_vote_history`, `app.db.collection.jobs.get_collection_job_for_owner`, `app.db.collection.reservations._reserve_repository_candidate_collection_job`, `app.db.search.jobs.admit_search`, `app.db.search.progress.read_search_progress`, `app.db.search.sessions.create_search_session`, `app.db.search.sessions._complete_search_session`, `app.db.search.sessions.latest_search_id`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `public_history.py`

<details>
<summary><code>HistoryPage.__post_init__</code> — Validate history page limits and offsets.</summary>

- Source: [public_history.py:18](../../backend/app/db/public_history.py#L18).
- Arguments: `self`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>HistoryPage.metadata</code> — Build bounded continuation metadata from the current page.</summary>

- Source: [public_history.py:24](../../backend/app/db/public_history.py#L24).
- Arguments: `self, has_more: bool`.
- Return annotation: `dict`.
- Return expressions: `{'history_truncated': has_more, 'limit': self.limit, 'offset': self.offset, 'next_offset': following if has_more and following <= 10000 else None}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>public_label</code> — Keep bounded model/format identifiers, excluding URLs and control characters.</summary>

- Source: [public_history.py:34](../../backend/app/db/public_history.py#L34).
- Arguments: `value: object, *, maximum: int=200`.
- Return annotation: `str`.
- Return expressions: `''; value if re.fullmatch('[A-Za-z0-9][A-Za-z0-9 ._:/+()-]*', value) else ''`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.collection.traces.safe_resource_key`, `app.db.collection.traces.safe_check`, `app.db.collection.traces.safe_observation`, `app.db.public_history.bounded_diagnostics`, `app.db.public_history.PublicVoteAttempt.from_row`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>public_timestamp</code> — Keep only a bounded timezone-aware timestamp.</summary>

- Source: [public_history.py:41](../../backend/app/db/public_history.py#L41).
- Arguments: `value: object`.
- Return annotation: `str \| None`.
- Return expressions: `None; value.isoformat()`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.collection.traces.safe_observation`, `app.db.public_history.bounded_diagnostics`, `app.db.public_history.PublicVoteAttempt.from_row`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>public_identifier</code> — Return a canonical UUID identifier or None for invalid input.</summary>

- Source: [public_history.py:54](../../backend/app/db/public_history.py#L54).
- Arguments: `value: object`.
- Return annotation: `str \| None`.
- Return expressions: `None; str(UUID(str(value))) if value is not None else None`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.public_history.PublicVoteAttempt.from_row`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>bounded_diagnostics</code> — Stored diagnostic fields and messages are untrusted, including legacy rows.</summary>

- Source: [public_history.py:61](../../backend/app/db/public_history.py#L61).
- Arguments: `values: object, *, stage: str='classification'`.
- Return annotation: `list[dict]`.
- Return expressions: `[]; result`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `public_history.public_label`, `public_history.public_timestamp`.
- Statically resolved callers: `app.db.collection.traces.safe_check`, `app.db.collection.traces.safe_observation`, `app.db.public_history.PublicVoteAttempt.from_row`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>PublicVoteAttempt.from_row</code> — Reconstruct a safe public attempt from untrusted stored fields.</summary>

- Source: [public_history.py:114](../../backend/app/db/public_history.py#L114).
- Arguments: `cls, row: dict`.
- Return annotation: `PublicVoteAttempt`.
- Return expressions: `cls(run_id=public_identifier(row.get('run_id')), voter_id=public_label(row.get('voter_id'), maximum=100), attempt=attempt if type(attempt) is int and attempt > 0 else 0, retry_cycle=public_identifier(row.get('retry_cycle')), model=public_label(row.get('model')), status=status, started_at=public_timestamp(row.get('started_at')), finished_at=public_timestamp(row.get('finished_at')), errors=errors, evidence='live' if row.get('evidence') == 'live' else 'legacy_snapshot')`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `public_history.bounded_diagnostics`, `public_history.public_identifier`, `public_history.public_label`, `public_history.public_timestamp`.
- Statically resolved callers: `app.db.classification.votes._read_vote_history`, `tests.test_backend_persistence_review.test_public_attempt_rebuilds_unsafe_legacy_values`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>PublicVoteAttempt.to_dict</code> — Serialize the public attempt dataclass.</summary>

- Source: [public_history.py:141](../../backend/app/db/public_history.py#L141).
- Arguments: `self`.
- Return annotation: `dict`.
- Return expressions: `asdict(self)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `schema.py`

<details>
<summary><code>init_database</code> — Apply the registered baseline and validate contracts before marking the pool ready.</summary>

- Source: [schema.py:118](../../backend/app/db/schema.py#L118).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`, `information_schema.tables`, `pg_indexes`, `schema_migrations`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`, `connection._set_initialized_pool`, `schema._apply_schema_migrations`.
- Statically resolved callers: `app.lifecycle.lifespan`, `app.migrate.run_migrations`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>validate_database_schema</code> — Initialize a runtime pool using an already migrated schema, without DDL.</summary>

- Source: [schema.py:126](../../backend/app/db/schema.py#L126).
- Arguments: ``.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`, `information_schema.tables`, `pg_indexes`, `schema_migrations`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`, `connection._set_initialized_pool`, `schema._schema_version`, `schema._validate_schema_contracts`.
- Statically resolved callers: `app.db.maintenance.maintain_database`, `app.lifecycle.lifespan`, `app.migrate.run_migrations`, `tests.test_backend_persistence_review.test_schema_validation_does_not_create_or_migrate_tables`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_apply_schema_migrations</code> — Run ordered migrations then validate the current schema contracts.</summary>

- Source: [schema.py:141](../../backend/app/db/schema.py#L141).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`, `information_schema.tables`, `pg_indexes`, `schema_migrations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._migration_for_version`, `schema._run_schema_migration`, `schema._schema_version`, `schema._validate_schema_contracts`.
- Statically resolved callers: `app.db.schema.init_database`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_validate_schema_contracts</code> — Check required tables, columns and indexes and reject obsolete columns.</summary>

- Source: [schema.py:172](../../backend/app/db/schema.py#L172).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`, `information_schema.tables`, `pg_indexes`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._assert_current_schema_has_no_obsolete_columns`, `schema._assert_current_schema_repository_persistence_exists`, `schema._assert_current_schema_search_index_exists`, `schema._assert_current_schema_tables_exist`.
- Statically resolved callers: `app.db.schema.validate_database_schema`, `app.db.schema._apply_schema_migrations`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_migration_for_version</code> — Select the registered version transition.</summary>

- Source: [schema.py:179](../../backend/app/db/schema.py#L179).
- Arguments: `version: int`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `migration_for_version(version)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `migrations.migration_for_version`.
- Statically resolved callers: `app.db.schema._apply_schema_migrations`, `tests.test_database.test_failed_initialization_rolls_back_schema_and_allows_retry`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_run_schema_migration</code> — Serialize initialization and apply one version transition atomically.</summary>

- Source: [schema.py:183](../../backend/app/db/schema.py#L183).
- Arguments: `connection: AsyncConnection[DictRow], source_version: int, target_version: int, migration`.
- Return annotation: `None`.
- Return expressions: `None`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`, `schema_migrations`.
- Ownership: opens connection: False; opens explicit transaction: True; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._assert_database_can_be_initialized`, `schema._schema_version`, `schema._set_schema_version`.
- Statically resolved callers: `app.db.schema._apply_schema_migrations`, `tests.test_database.test_schema_migration_rechecks_version_after_acquiring_lock`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_assert_database_can_be_initialized</code> — Reject initialization over unmanaged application tables.</summary>

- Source: [schema.py:214](../../backend/app/db/schema.py#L214).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._existing_managed_tables`.
- Statically resolved callers: `app.db.schema._run_schema_migration`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_existing_managed_tables</code> — Find managed tables already present in the current schema.</summary>

- Source: [schema.py:226](../../backend/app/db/schema.py#L226).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `tuple[str, ...]`.
- Return expressions: `tuple(existing_tables)`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._table_exists`.
- Statically resolved callers: `app.db.schema._assert_database_can_be_initialized`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_missing_managed_tables</code> — Find required tables absent from the current schema.</summary>

- Source: [schema.py:236](../../backend/app/db/schema.py#L236).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `tuple[str, ...]`.
- Return expressions: `tuple(missing_tables)`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._table_exists`.
- Statically resolved callers: `app.db.schema._assert_current_schema_tables_exist`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_assert_current_schema_tables_exist</code> — Reject a schema version whose required tables are missing.</summary>

- Source: [schema.py:246](../../backend/app/db/schema.py#L246).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `schema._missing_managed_tables`.
- Statically resolved callers: `app.db.schema._validate_schema_contracts`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_assert_current_schema_repository_persistence_exists</code> — Validate the required repository persistence columns and indexes.</summary>

- Source: [schema.py:258](../../backend/app/db/schema.py#L258).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`, `pg_indexes`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`.
- Statically resolved callers: `app.db.schema._validate_schema_contracts`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_assert_current_schema_has_no_obsolete_columns</code> — Reject retired collected-dataset columns.</summary>

- Source: [schema.py:300](../../backend/app/db/schema.py#L300).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`.
- Statically resolved callers: `app.db.schema._validate_schema_contracts`, `tests.test_database.test_current_schema_rejects_obsolete_collected_dataset_columns`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_assert_current_schema_search_index_exists</code> — Require the catalogue tsvector column and GIN search index.</summary>

- Source: [schema.py:322](../../backend/app/db/schema.py#L322).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `information_schema.columns`, `pg_indexes`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.schema._validate_schema_contracts`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_table_exists</code> — Check whether a table exists in the current schema.</summary>

- Source: [schema.py:362](../../backend/app/db/schema.py#L362).
- Arguments: `connection: AsyncConnection[DictRow], table_name: str`.
- Return annotation: `bool`.
- Return expressions: `row is not None and bool(row['table_exists'])`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.schema._existing_managed_tables`, `app.db.schema._missing_managed_tables`, `app.db.schema._schema_version`, `tests.test_database.test_table_exists_checks_current_schema_only`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_require_current_schema</code> — Startup validates the schema once for this pool; business calls do no SQL here.</summary>

- Source: [schema.py:381](../../backend/app/db/schema.py#L381).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_initialized`.
- Statically resolved callers: `app.db.catalog.datasets.save_collected_datasets`, `app.db.catalog.datasets.get_collected_datasets`, `app.db.catalog.observations.list_dataset_discovery_observations`, `app.db.catalog.search.search_collected_datasets`, `app.db.classification.candidates.save_repository_candidates`, `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.classification.candidates.claim_candidate_classification`, `app.db.classification.candidates.fail_candidate_classification`, `app.db.classification.candidates.mark_interrupted_candidate_classifications_error`, `app.db.classification.completion.complete_candidate_classification`, `app.db.collection.completion.complete_collection_job`, `app.db.collection.jobs.create_collection_job`, `app.db.collection.jobs.get_collection_job_for_owner`, `app.db.collection.jobs.mark_interrupted_collection_jobs_error`, `app.db.collection.jobs.claim_pending_collection_job`, `app.db.collection.jobs.get_collection_job`, `app.db.collection.jobs.mark_collection_job_running`, `app.db.collection.jobs.mark_collection_job_done`, `app.db.collection.jobs.mark_collection_job_error`, `app.db.collection.reservations.reserve_repository_candidate_collection_job`, `app.db.execution.quotas.consume_api_quota`, `app.db.execution.quotas.consume_quota_limits`, `app.db.search.jobs.admit_search`, `app.db.search.jobs.claim_search`, `app.db.search.sessions.create_search_session`, `app.db.search.sessions.complete_search_session`, `app.db.search.sessions.mark_interrupted_search_sessions_error`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_schema_version</code> — Read the current schema version, treating an absent version table as zero.</summary>

- Source: [schema.py:386](../../backend/app/db/schema.py#L386).
- Arguments: `connection: AsyncConnection[DictRow]`.
- Return annotation: `int`.
- Return expressions: `0; int(row['version'])`.
- Tables referenced directly or through resolved DB helpers: `information_schema.tables`, `schema_migrations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `schema._table_exists`.
- Statically resolved callers: `app.db.schema.validate_database_schema`, `app.db.schema._apply_schema_migrations`, `app.db.schema._run_schema_migration`, `tests.test_database._schema_version`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_set_schema_version</code> — Record a completed version transition on the migration connection.</summary>

- Source: [schema.py:399](../../backend/app/db/schema.py#L399).
- Arguments: `connection: AsyncConnection[DictRow], version: int`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `schema_migrations`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.schema._run_schema_migration`, `tests.test_database.test_init_database_rejects_current_version_with_missing_managed_tables`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `search/admission.py`

<details>
<summary><code>admit_search</code> — Admit or replay one owned command; quotas, work and receipt commit together.</summary>

- Source: [search/admission.py:20](../../backend/app/db/search/admission.py#L20).
- Arguments: `owner_id: str, key: str, *, query: str='', access_mode: str, client_key: str \| None, retry_search_id: UUID \| None=None`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `(None, False); (row, False); (row, True)`.
- Tables referenced directly or through resolved DB helpers: `api_commands`, `api_rate_limits`, `repository_candidates`, `search_local_results`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_pool`, `execution.commands.read_command`, `execution.commands.record_command`, `execution.quotas.reserve_quota_limits`, `schema._require_current_schema`, `search.sessions._normalized_owner_id`.
- Statically resolved callers: `app.api.routes.searches._admit_search_command`, `tests.test_async_searches.admit`, `tests.test_async_searches.test_unsupported_search_access_mode_is_rejected`, `tests.test_worker_claims.enqueue`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `search/completion.py`

<details>
<summary><code>complete_discovery</code> — Publish associations/candidates, quotas and discovery outcome as one transaction.</summary>

- Source: [search/completion.py:29](../../backend/app/db/search/completion.py#L29).
- Arguments: `job, result`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `False; True`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`, `collection_jobs`, `repository_candidates`, `search_local_results`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._save_repository_candidates`, `connection._require_database_pool`, `execution.quotas.lock_work_admission`, `execution.quotas.reserve_work`, `search.jobs._lock_attempt`, `search.sessions._complete_search_session`, `search.sessions.save_local_results`.
- Statically resolved callers: `app.workers.search.worker.SearchWorker.execute`, `tests.test_async_searches.test_restart_preserves_queue_fences_old_attempt_and_late_command_replay`, `tests.test_async_searches.test_public_quota_is_once_per_attempt_and_retry_after_is_enforced`, `tests.test_async_searches.test_failed_downstream_admission_publishes_nothing`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>complete_search_session</code> — Move a running search to one terminal state without overwriting it.</summary>

- Source: [search/completion.py:73](../../backend/app/db/search/completion.py#L73).
- Arguments: `search_id: UUID, owner_id: str, *, origin: SearchOrigin, status: SearchStatus='completed', error: str='', errors: list[dict] \| None=None, local_result_count: int \| None=None, discovery_complete: bool \| None=None, warnings: list[dict] \| None=None, local_dataset_ids: list[int] \| None=None`.
- Return annotation: `dict[str, object]`.
- Return expressions: `_search_session_to_dict(row)`.
- Tables referenced directly or through resolved DB helpers: `search_local_results`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`, `schema._require_current_schema`, `search.sessions._complete_search_session`, `search.sessions._search_session_to_dict`, `search.sessions.save_local_results`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_complete_search_session</code> — Save a terminal search state only while the owned session is running.</summary>

- Source: [search/completion.py:111](../../backend/app/db/search/completion.py#L111).
- Arguments: `connection: AsyncConnection[DictRow], search_id: UUID, owner_id: str, *, origin: SearchOrigin, status: SearchStatus, error: str='', errors: list[dict] \| None=None, local_result_count: int \| None=None, discovery_complete: bool \| None=None, warnings: list[dict] \| None=None`.
- Return annotation: `Row \| None`.
- Return expressions: `await _fetchone(connection, "\n        UPDATE search_sessions\n        SET origin = %s,\n            status = %s,\n            error = %s,\n            errors = %s, local_result_count = %s, discovery_complete = %s,\n            warnings = %s, attempt_token = NULL, retry_at = NULL,\n            updated_at = NOW(),\n            finished_at = NOW()\n        WHERE id = %s AND owner_id = %s AND status = 'running'\n        RETURNING id, query, origin, status, error, errors,\n                  local_result_count, discovery_complete,\n                  created_at, updated_at, finished_at\n        ", (origin, status, normalized_error, _jsonb(errors or ([Diagnostic('processing_failed', 'search').to_dict()] if status == 'error' else [])), local_result_count, discovery_complete if discovery_complete is not None else status == 'completed', _jsonb(warnings or []), search_id, _normalized_owner_id(owner_id)))`.
- Tables referenced directly or through resolved DB helpers: `search_sessions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `search.sessions._normalized_owner_id`, `serialization._jsonb`.
- Statically resolved callers: `app.db.classification.candidates.complete_search_session_with_repository_candidates`, `app.db.search.jobs.complete_discovery`, `app.db.search.sessions.complete_search_session`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>save_local_results</code> — Associate existing dataset IDs in their result order using the caller's transaction.</summary>

- Source: [search/completion.py:160](../../backend/app/db/search/completion.py#L160).
- Arguments: `connection, search_id, dataset_ids`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: `search_local_results`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.search.jobs.complete_discovery`, `app.db.search.sessions.complete_search_session`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>complete_search_session_with_repository_candidates</code> — Persist and enqueue online candidates, then finish their search atomically.</summary>

- Source: [search/completion.py:174](../../backend/app/db/search/completion.py#L174).
- Arguments: `search_id: UUID, owner_id: str, candidates: list[RepositorySearchResult], *, status: SearchStatus, errors: list[dict] \| None=None, discovery_complete: bool \| None=None, warnings: list[dict] \| None=None, admission: WorkAdmission \| None=None`.
- Return annotation: `list[dict[str, object]]`.
- Return expressions: `[_repository_candidate_to_dict(row) for row in rows]`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`, `collection_jobs`, `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._repository_candidate_to_dict`, `classification.candidates._save_repository_candidates`, `connection._require_database_pool`, `execution.quotas.lock_work_admission`, `execution.quotas.reserve_work`, `schema._require_current_schema`, `search.sessions._complete_search_session`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `search/jobs.py`

<details>
<summary><code>claim_search</code> — Claim or recover discovery with one token; commit the task and receipt together.</summary>

- Source: [search/jobs.py:18](../../backend/app/db/search/jobs.py#L18).
- Arguments: `*, claim_token: UUID \| None=None`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `await _fetchone(connection, "SELECT * FROM search_sessions\n                       WHERE id = %s AND status = 'running' AND updated_at = %s", (UUID(receipt['resource_id']), receipt['claim_version'])); row`.
- Tables referenced directly or through resolved DB helpers: `application_ownership`, `search_sessions`, `worker_claims`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_pool`, `execution.worker_claims.read_worker_claim`, `execution.worker_claims.record_worker_claim`, `schema._require_current_schema`.
- Statically resolved callers: `app.workers.search.worker.SearchWorker.claim`, `tests.test_application_lock.test_missing_or_inactive_generation_rejects_claim`, `tests.test_async_searches.test_local_ranked_results_and_legacy_completion_are_atomic`, `tests.test_async_searches.test_empty_vs_unavailable_discovery_and_durable_warning`, `tests.test_async_searches.test_partial_datacite_warning_and_usable_candidates_survive_restart`, `tests.test_async_searches.test_restart_preserves_queue_fences_old_attempt_and_late_command_replay`, `tests.test_async_searches.test_public_quota_is_once_per_attempt_and_retry_after_is_enforced`, `tests.test_async_searches.test_commit_ack_loss_does_not_repeat_provider_or_downstream_quota`, `tests.test_async_searches.test_failed_downstream_admission_publishes_nothing`, `tests.test_async_searches.test_reinitialization_does_not_reschedule_completed_inline_search`, `tests.test_public_quotas.execute_next_search`, `tests.test_standalone_api_failures.test_full_queue_rejects_without_receipt_and_replay_survives_pool_restart`, `tests.test_worker_claims.test_replacement_waits_for_inflight_claim_commit_before_recovery`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_lock_attempt</code> — Lock the search only if owner, running state and attempt identity still match.</summary>

- Source: [search/jobs.py:52](../../backend/app/db/search/jobs.py#L52).
- Arguments: `connection, job`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `await _fetchone(connection, "\n        SELECT * FROM search_sessions WHERE id = %s AND owner_id = %s AND status = 'running'\n            AND attempt_token = %s AND attempt_number = %s FOR UPDATE\n    ", (job['id'], job['owner_id'], job['attempt_token'], job['attempt_number']))`.
- Tables referenced directly or through resolved DB helpers: `search_sessions`.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: True. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`.
- Statically resolved callers: `app.db.search.jobs.reserve_external_search`, `app.db.search.jobs.complete_discovery`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>reserve_external_search</code> — An acknowledged reservation survives a lost commit reply; no double charge.</summary>

- Source: [search/jobs.py:63](../../backend/app/db/search/jobs.py#L63).
- Arguments: `job`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `False; True`.
- Tables referenced directly or through resolved DB helpers: `api_rate_limits`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._require_database_pool`, `execution.quotas.reserve_quota_limits`, `search.jobs._lock_attempt`.
- Statically resolved callers: `app.workers.search.worker.SearchWorker.execute`, `tests.test_async_searches.test_public_quota_is_once_per_attempt_and_retry_after_is_enforced`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>fail_discovery</code> — Record discovery failure only for the matching owner, attempt number and token.</summary>

- Source: [search/jobs.py:84](../../backend/app/db/search/jobs.py#L84).
- Arguments: `job, *, origin, error, diagnostics, retry_at=None`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `await _fetchone(connection, "\n            UPDATE search_sessions SET status = 'error', origin = %s, error = %s, errors = %s,\n                discovery_complete = FALSE, retry_at = %s, attempt_token = NULL,\n                updated_at = NOW(), finished_at = NOW()\n            WHERE id = %s AND owner_id = %s AND status = 'running'\n                AND attempt_token = %s AND attempt_number = %s RETURNING id\n        ", (origin, error, _jsonb(diagnostics), retry_at, job['id'], job['owner_id'], job['attempt_token'], job['attempt_number']))`.
- Tables referenced directly or through resolved DB helpers: `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_pool`, `serialization._jsonb`.
- Statically resolved callers: `app.workers.search.worker.SearchWorker.execute`, `app.workers.search.worker.SearchWorker.recover`, `tests.test_async_searches.test_restart_preserves_queue_fences_old_attempt_and_late_command_replay`, `tests.test_worker_claims.fail`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>mark_interrupted_search_sessions_error</code> — Close searches abandoned by a previous single application process.</summary>

- Source: [search/jobs.py:109](../../backend/app/db/search/jobs.py#L109).
- Arguments: ``.
- Return annotation: `int`.
- Return expressions: `len(rows)`.
- Tables referenced directly or through resolved DB helpers: `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchall`, `connection._require_database_pool`, `schema._require_current_schema`, `serialization._jsonb`.
- Statically resolved callers: `app.lifecycle.lifespan`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `search/progress.py`

<details>
<summary><code>read_search_progress</code> — Read one owner's search and follow-up from a single consistent snapshot.</summary>

- Source: [search/progress.py:14](../../backend/app/db/search/progress.py#L14).
- Arguments: `search_id: UUID, owner_id: str`.
- Return annotation: `tuple[Row, list[Row], dict[UUID, CollectionJobReservation]] \| None`.
- Return expressions: `(search, candidates, collections); None`.
- Tables referenced directly or through resolved DB helpers: `collected_datasets`, `collection_job_candidates`, `collection_jobs`, `dataset_discovery_observations`, `repository_candidates`, `search_local_results`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: True; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `classification.candidates._repository_candidate_to_dict`, `collection.jobs._collection_job_to_dict`, `connection._fetchall`, `connection._fetchone`, `connection._require_database_pool`, `search.sessions._normalized_owner_id`.
- Statically resolved callers: `app.api.search_progress.load_search_progress`, `tests.test_worker_persistence.test_vote_progress_and_polling_preserve_completion_claim`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

## `search/sessions.py`

<details>
<summary><code>create_search_session</code> — Create the durable record that owns one local-then-online search.</summary>

- Source: [search/sessions.py:19](../../backend/app/db/search/sessions.py#L19).
- Arguments: `query: str, owner_id: str`.
- Return annotation: `dict[str, object]`.
- Return expressions: `_search_session_to_dict(row)`.
- Tables referenced directly or through resolved DB helpers: `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_pool`, `schema._require_current_schema`, `search.sessions._normalized_owner_id`, `search.sessions._search_session_to_dict`.
- Statically resolved callers: none; callbacks and fixture exports require source/test inspection.
- Direct call sites in application-code files: False; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>latest_search_id</code> — Return the owner's latest search ID, optionally requiring saved candidates.</summary>

- Source: [search/sessions.py:46](../../backend/app/db/search/sessions.py#L46).
- Arguments: `owner_id, *, with_candidates=False`.
- Return annotation: `unannotated; see return expressions`.
- Return expressions: `row['id'] if row else None`.
- Tables referenced directly or through resolved DB helpers: `repository_candidates`, `search_sessions`.
- Ownership: opens connection: True; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `connection._fetchone`, `connection._require_database_pool`, `search.sessions._normalized_owner_id`.
- Statically resolved callers: `app.api.routes.searches.get_latest_search`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_search_session_to_dict</code> — Serialize the search row with UUID and timestamp conversion.</summary>

- Source: [search/sessions.py:67](../../backend/app/db/search/sessions.py#L67).
- Arguments: `row: Row`.
- Return annotation: `dict[str, object]`.
- Return expressions: `{'id': UUID(str(row['id'])), 'query': str(row['query']), 'origin': str(row['origin']), 'status': str(row['status']), 'error': str(row['error']), 'errors': row.get('errors', []), 'local_result_count': row.get('local_result_count'), 'discovery_complete': row.get('discovery_complete'), 'created_at': _format_timestamp(row['created_at']), 'updated_at': _format_timestamp(row['updated_at']), 'finished_at': _format_optional_timestamp(row['finished_at'])}`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._format_optional_timestamp`, `serialization._format_timestamp`.
- Statically resolved callers: `app.db.search.sessions.create_search_session`, `app.db.search.sessions.complete_search_session`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

## `serialization.py`

<details>
<summary><code>_serialize_discovery_methods</code> — Validate tuple discovery methods and encode them as strict JSONB.</summary>

- Source: [serialization.py:17](../../backend/app/db/serialization.py#L17).
- Arguments: `discovery_methods: tuple[str, ...]`.
- Return annotation: `Jsonb`.
- Return expressions: `_jsonb(_normalize_string_items_for_storage(discovery_methods, 'discovery method'))`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._jsonb`, `serialization._normalize_string_items_for_storage`.
- Statically resolved callers: `app.db.collection.jobs._mark_collection_job_done`, `tests.test_database.test_discovery_methods_json_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_deserialize_discovery_methods</code> — Validate and decode the stored discovery-method array.</summary>

- Source: [serialization.py:26](../../backend/app/db/serialization.py#L26).
- Arguments: `value: object`.
- Return annotation: `list[str]`.
- Return expressions: `_normalize_string_items_from_storage(data, 'collection_jobs.discovery_methods', 'discovery methods')`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._deserialize_json_array`, `serialization._normalize_string_items_from_storage`.
- Statically resolved callers: `app.db.collection.jobs._collection_job_to_dict`, `tests.test_database.test_discovery_methods_json_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_serialize_geography</code> — Validate tuple geography values and encode strict JSONB.</summary>

- Source: [serialization.py:39](../../backend/app/db/serialization.py#L39).
- Arguments: `geography: tuple[str, ...]`.
- Return annotation: `Jsonb`.
- Return expressions: `_jsonb(_normalize_string_items_for_storage(geography, 'geography'))`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._jsonb`, `serialization._normalize_string_items_for_storage`.
- Statically resolved callers: `app.db.catalog.datasets._upsert_collected_dataset`, `tests.test_database.test_discovery_methods_json_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_deserialize_geography</code> — Validate and decode the saved geography array.</summary>

- Source: [serialization.py:48](../../backend/app/db/serialization.py#L48).
- Arguments: `value: object`.
- Return annotation: `list[str]`.
- Return expressions: `_normalize_string_items_from_storage(data, 'collected_datasets.geography', 'geography')`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._deserialize_json_array`, `serialization._normalize_string_items_from_storage`.
- Statically resolved callers: `app.db.catalog.datasets._collected_dataset_from_rows`, `tests.test_database.test_discovery_methods_json_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_serialize_signals</code> — Require a JSON object with string keys before encoding model signals.</summary>

- Source: [serialization.py:61](../../backend/app/db/serialization.py#L61).
- Arguments: `signals: dict[str, object]`.
- Return annotation: `Jsonb`.
- Return expressions: `_jsonb(signals)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._assert_json_object_keys_are_strings`, `serialization._jsonb`.
- Statically resolved callers: `app.db.catalog.datasets._upsert_collected_dataset`, `app.db.catalog.distributions._upsert_collected_distribution`, `tests.test_database.test_discovery_methods_json_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_deserialize_signals</code> — Decode stored signals and require an object.</summary>

- Source: [serialization.py:73](../../backend/app/db/serialization.py#L73).
- Arguments: `value: object, field_name: str='signals'`.
- Return annotation: `dict[str, object]`.
- Return expressions: `data`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.datasets._collected_dataset_from_rows`, `app.db.classification.candidates._repository_candidate_to_dict`, `tests.test_database.test_signal_json_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_jsonb</code> — Validate JSON serializability and construct the PostgreSQL JSONB adapter.</summary>

- Source: [serialization.py:99](../../backend/app/db/serialization.py#L99).
- Arguments: `value: object`.
- Return annotation: `Jsonb`.
- Return expressions: `Jsonb(value, dumps=_json_dumps)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._json_dumps`.
- Statically resolved callers: `app.db.classification.candidates._save_repository_candidates`, `app.db.classification.candidates._complete_candidate_classification`, `app.db.classification.candidates.fail_candidate_classification`, `app.db.classification.candidates.mark_interrupted_candidate_classifications_error`, `app.db.classification.votes.prepare_vote_run`, `app.db.classification.votes.finish_vote`, `app.db.classification.votes._publish_progress`, `app.db.classification.votes.mark_interrupted_votes_error`, `app.db.collection.jobs.mark_interrupted_collection_jobs_error`, `app.db.collection.jobs._mark_collection_job_done`, `app.db.collection.jobs.mark_collection_job_error`, `app.db.collection.traces.write_collection_trace`, `app.db.execution.commands.record_command`, `app.db.execution.retries.schedule_llm_retry`, `app.db.search.jobs.fail_discovery`, `app.db.search.sessions.mark_interrupted_search_sessions_error`, `app.db.search.sessions._complete_search_session`, `app.db.serialization._serialize_discovery_methods`, `app.db.serialization._serialize_geography`, `app.db.serialization._serialize_signals`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_json_dumps</code> — Serialize strict JSON with sorted keys and no nonfinite numbers.</summary>

- Source: [serialization.py:108](../../backend/app/db/serialization.py#L108).
- Arguments: `value: object`.
- Return annotation: `str`.
- Return expressions: `json.dumps(value, allow_nan=False, sort_keys=True)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.serialization._jsonb`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_deserialize_json_array</code> — Decode stored JSON and require an array.</summary>

- Source: [serialization.py:112](../../backend/app/db/serialization.py#L112).
- Arguments: `value: object, field_name: str, field_label: str`.
- Return annotation: `list[object]`.
- Return expressions: `data; value`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.classification.candidates._repository_candidate_to_dict`, `app.db.serialization._deserialize_discovery_methods`, `app.db.serialization._deserialize_geography`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_normalize_string_items_for_storage</code> — Require tuple input before validating stored text values.</summary>

- Source: [serialization.py:138](../../backend/app/db/serialization.py#L138).
- Arguments: `value: tuple[str, ...], item_label: str`.
- Return annotation: `list[str]`.
- Return expressions: `_normalize_string_items(list(value), f'Invalid {item_label} items before storage')`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._normalize_string_items`.
- Statically resolved callers: `app.db.serialization._serialize_discovery_methods`, `app.db.serialization._serialize_geography`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_normalize_string_items_from_storage</code> — Validate string values read from a stored array.</summary>

- Source: [serialization.py:154](../../backend/app/db/serialization.py#L154).
- Arguments: `value: list[object], field_name: str, field_label: str`.
- Return annotation: `list[str]`.
- Return expressions: `_normalize_string_items(value, f'Invalid JSON items in stored {field_label} field {field_name}')`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._normalize_string_items`.
- Statically resolved callers: `app.db.serialization._deserialize_discovery_methods`, `app.db.serialization._deserialize_geography`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_normalize_string_items</code> — Reject nonstrings or blanks, then trim and deduplicate text values.</summary>

- Source: [serialization.py:165](../../backend/app/db/serialization.py#L165).
- Arguments: `value: list[object], error_prefix: str`.
- Return annotation: `list[str]`.
- Return expressions: `list(dict.fromkeys(normalized_items))`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.serialization._normalize_string_items_for_storage`, `app.db.serialization._normalize_string_items_from_storage`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_assert_json_object_keys_are_strings</code> — Recursively reject nonstring keys in JSON objects.</summary>

- Source: [serialization.py:195](../../backend/app/db/serialization.py#L195).
- Arguments: `value: object, path: str`.
- Return annotation: `None`.
- Return expressions: `implicit None / generator yield`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._assert_json_object_keys_are_strings`.
- Statically resolved callers: `app.db.serialization._serialize_signals`, `app.db.serialization._assert_json_object_keys_are_strings`.
- Direct call sites in application-code files: True; in test files: False. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_format_timestamp</code> — Require a timezone-aware datetime and format it as ISO 8601.</summary>

- Source: [serialization.py:211](../../backend/app/db/serialization.py#L211).
- Arguments: `value: object`.
- Return annotation: `str`.
- Return expressions: `value.isoformat()`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: none resolved.
- Statically resolved callers: `app.db.catalog.datasets._collected_dataset_from_rows`, `app.db.catalog.observations._dataset_discovery_observation_to_dict`, `app.db.classification.candidates._repository_candidate_to_dict`, `app.db.collection.jobs._collection_job_to_dict`, `app.db.search.sessions._search_session_to_dict`, `app.db.serialization._format_optional_timestamp`, `tests.test_database.test_timestamp_formatting_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>

<details>
<summary><code>_format_optional_timestamp</code> — Format an optional timestamp, using the existing empty-string representation.</summary>

- Source: [serialization.py:226](../../backend/app/db/serialization.py#L226).
- Arguments: `value: object`.
- Return annotation: `str`.
- Return expressions: `''; _format_timestamp(value)`.
- Tables referenced directly or through resolved DB helpers: none statically identified; generic SQL helpers use caller SQL.
- Ownership: opens connection: False; opens explicit transaction: False; receives connection: False. Connection-taking mutation helpers preserve their caller transaction; pool defaults remain autocommit.
- Direct DB helper dependencies: `serialization._format_timestamp`.
- Statically resolved callers: `app.db.catalog.datasets._collected_dataset_from_rows`, `app.db.collection.jobs._collection_job_to_dict`, `app.db.search.sessions._search_session_to_dict`, `tests.test_database.test_timestamp_formatting_errors_are_explicit`.
- Direct call sites in application-code files: True; in test files: True. These flags describe source locations, not a proof of runtime reachability.

</details>
