# Global Health Dataset Catalog - Onboarding

> Last verified: 2026-09-02.

This guide is the shortest path from a fresh checkout to understanding and
running the application. Detailed contracts and diagrams live in the
[documentation index](../README.md#documentation).

## 1. Project in 30 Seconds

The project discovers health dataset candidates, classifies them with three LLM
voters, validates data links, and stores accepted collection results in
PostgreSQL.

It has two distinct user flows:

1. **Repository search** queries DataCite and classifies each returned record for
   relevance to the user's query. Accepted results are displayed as candidates;
   they are not persisted.
2. **Source collection** discovers records from a configured source, classifies
   each record as an individual health dataset, validates at least one file or
   API distribution, and persists successful results.

The word "official" is not an enforced quality guarantee. The seed catalogue
contains official organizations, but arbitrary sources can be added and no full
source-trust policy is implemented yet.

## 2. Runtime Architecture

```text
React/Vite frontend
        |
        v
FastAPI routes
        |
        +--> repository search and repository LLM ensemble
        |
        +--> background collection job
                  |
                  +--> discovery adapters
                  +--> page LLM ensemble
                  +--> distribution validation
                  +--> atomic PostgreSQL completion
```

Main ownership boundaries:

- `frontend/src/`: repository search, source catalogue, job progress, and saved
  dataset views;
- `backend/app/routes/`: HTTP contracts and background-job orchestration;
- `backend/app/db/`: PostgreSQL connection, schema, jobs, and persistence;
- `collector/discovery/`: structured and generic discovery adapters;
- `collector/classification/`: LLM clients, prompts, classifiers, and ensembles;
- `collector/repository_search/`: DataCite search, normalization, filtering, and
  repository-result classification;
- `collector/validation/`: lightweight file/API link validation.

For diagrams, see [Collector Pipeline Diagram](collector-pipeline-diagram.md),
[Classification Architecture](classification-architecture.md), and
[Database Schema Diagram](database-schema-diagram.md).

## 3. Repository Structure

```text
backend/
  app/
    main.py
    database.py                 compatibility facade
    db/
      connection.py
      schema.py
      sources.py
      collection_jobs.py
      collection_completion.py
      collected_datasets.py
    routes/
      sources.py
      collector.py

collector/
  main.py                       source collection pipeline
  fetch.py                      SSRF-protected public HTTP fetch
  classification/
    factory.py
    ensemble.py
    llm_client.py
    page_llm_classifier.py
    repository_llm_classifier.py
    prompts.py
  discovery/
    adapters/
    sitemap.py
  repository_search/
    models.py
    filtering.py
    service.py
    providers/datacite.py
  validation/downloads.py

frontend/src/
  App.jsx
  components/
    RepositorySearchSection.jsx
    RepositoryAcceptedCard.jsx
    RepositoryProgressCard.jsx
    SourceCatalogSection.jsx
    CollectedDatasetsSection.jsx

tests/
```

## 4. Repository Search

`POST /collector/search-repositories` calls
`repository_search/service.py:search_repository_metadata()`.

Current behavior:

1. DataCite is the only default provider.
2. The provider requests `resource-type-id=dataset` and sorts by relevance.
3. Results without a title or syntactically valid HTTP(S) URL are removed.
4. A provider failure is logged and returned as a warning when another provider
   succeeds. If every provider fails, the request fails.
5. The frontend progressively calls
   `POST /collector/classify-repository-result` for each candidate.
6. Three distinct OpenAI models vote; two positive votes are required.
7. `relevant` and `somewhat_relevant` are positive repository votes.

The repository prompt evaluates relevance to the search query. It does not
independently establish health relevance, source trust, file availability, or
publication eligibility. Repository candidates are not written to PostgreSQL.

## 5. Source Discovery

`POST /collector/collection-jobs` creates a background job. The collector then
calls `collect_source_with_report()` in `collector/main.py`.

Discovery prefers structured metadata from CKAN, Socrata, and data.json/DCAT
before generic HTML and sitemap fallbacks. Dataverse is not registered in the
active adapter tuple and remains future work. The collector limits how many
pages and distributions it analyzes using `CollectorConfig`. Adapter-specific
behavior belongs in `collector/discovery/`, not in the core classifier.

## 6. LLM Classification

Classification is implemented, not a future feature. Two separate ensembles
share the same three configured OpenAI models:

- `EnsembleRepositoryRelevanceClassifier` judges query relevance for repository
  candidates;
- `EnsemblePageClassifier` judges whether a discovered page is an individual,
  health-relevant dataset.

Both defaults use:

```text
votes_required = 2
minimum_successful_votes = 2
```

This permits one model failure while still requiring a two-model majority. The
three model names must be distinct, but all voters use the same OpenAI provider
and API key; this is model diversity, not provider independence.

See [Classification Architecture](classification-architecture.md) for exact
prompts, payloads, output schemas, failure handling, and parameter traces.

## 7. Distribution Validation

After page acceptance, the collector validates candidate files and APIs:

1. send `HEAD`;
2. use a bounded partial `GET` when `HEAD` is unsupported or inconclusive;
3. require an HTTP status from 200 through 399;
4. reject HTML responses for non-API distributions;
5. infer a format from headers or a small body sample when possible.

This verifies lightweight accessibility, not scientific correctness or complete
file integrity. The project does not download and retain dataset files.

All untrusted collector fetches use the public-HTTP guard in
`collector/fetch.py`. Initial URLs and every redirect are checked so private,
loopback, link-local, multicast, reserved, and unspecified addresses are
blocked.

## 8. Persistence Decision

A discovered result reaches PostgreSQL only when:

```text
page ensemble accepted it with at least 2 positive votes
AND
at least one considered distribution validated successfully
```

Collection and LLM calls run outside a database transaction. Once the complete
`CollectionResult` exists, `complete_collection_job()` opens one PostgreSQL
transaction, upserts every accepted dataset, and marks the job `done`. Any
persistence failure rolls back both the dataset writes and the `done` status.

Datasets are deduplicated only by exact `dataset_url`. DOI-, title-, version-,
and mirror-aware deduplication are not implemented.

## 9. Database

The application is PostgreSQL-only and requires `DATABASE_URL`. At startup it:

1. opens the async connection pool;
2. checks `schema_migrations`;
3. creates the current schema only for an empty database;
4. inserts system seed sources.

It deliberately refuses obsolete or partially managed schemas. Historical
SQLite behavior is documented in
[ADR 0001](adr/0001-postgresql-only.md), not in this runtime guide.

## 10. HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process health response |
| GET | `/sources` | List configured sources |
| POST | `/sources` | Add a source |
| GET | `/sources/{id}/page` | Redirect to source page |
| POST | `/collector/search-repositories` | Search DataCite metadata |
| POST | `/collector/classify-repository-result` | Classify one candidate |
| POST | `/collector/collection-jobs` | Start source collection |
| GET | `/collector/collection-jobs/{id}` | Read job status |
| GET | `/collector/collected-datasets` | List persisted datasets |

## 11. Run Locally

From the repository root:

```bash
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
export POSTGRES_PASSWORD="change-me-locally"
docker compose up -d postgres

export DATABASE_URL="postgresql://global_health:${POSTGRES_PASSWORD}@127.0.0.1:5432/global_health"
export OPENAI_API_KEY="your-api-key"
export OPENAI_CLASSIFIER_MODEL_1="model-a"
export OPENAI_CLASSIFIER_MODEL_2="model-b"
export OPENAI_CLASSIFIER_MODEL_3="model-c"
```

The model values are examples: use three distinct model names available to the
configured OpenAI account.

Backend:

```bash
cd backend
DATABASE_URL="$DATABASE_URL" PYTHONPATH=.. \
  ../.venv/bin/python -m uvicorn app.main:app --reload --port 8001
```

Frontend, in another terminal:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

Open `http://127.0.0.1:5173/`.

## 12. Tests and Checks

```bash
.venv/bin/ruff check .
.venv/bin/pytest
npm --prefix frontend run build
```

Last verified without `TEST_DATABASE_URL`: **117 passed, 33 skipped**. The skipped
tests require PostgreSQL. Run the complete database suite with:

```bash
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/pytest
```

Test counts are observations, not a permanent contract; update this line when
the suite changes.

## 13. Current Limits

| Limit | Current value |
| --- | ---: |
| Outbound request timeout | 10 seconds |
| Pages analyzed per source | 5 |
| Distributions validated per dataset | 1 |
| Distribution partial-GET sample | 65,536 bytes |
| HTML response | 1,000,000 bytes |
| JSON or sitemap response | 5,000,000 bytes |
| Sitemaps traversed per source | 10 |
| Sitemap URLs returned by the active generic adapter | 50 |
| Sitemap utility hard cap | 1,000 |

- repository search candidates are display-only and are not fed automatically
  into source collection;
- repository classification does not independently enforce health relevance;
- source authority and the word "official" are not enforced;
- licensing is extracted when available but no allow/deny policy is enforced;
- duplicate handling uses exact dataset URLs only;
- authentication, production deployment, monitoring, scheduled revalidation,
  and human review workflows are not implemented.

The proposed controls are tracked in the
[Dataset Collection & Quality Policy](dataset-collection-and-quality-policy.md)
and [Roadmap](roadmap.md).

## 14. Recommended Reading Order

1. `README.md`
2. `frontend/src/App.jsx` and `frontend/src/components/`
3. `backend/app/routes/collector.py`
4. `collector/main.py`
5. `collector/repository_search/service.py`
6. `collector/classification/factory.py` and `ensemble.py`
7. `collector/classification/prompts.py`
8. `collector/validation/downloads.py` and `collector/fetch.py`
9. `backend/app/db/collection_completion.py`
10. tests corresponding to the code being changed

The mental model to retain is:

```text
repository search = candidate relevance and display
source collection = dataset + health classification + link validation + storage
```
