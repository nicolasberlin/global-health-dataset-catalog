# Global Health Dataset Catalog

Small React + FastAPI app for discovering and cataloging health dataset pages.
Some seeded sources are official organizations, but the application does not
currently enforce official publisher status for every collected record.

The tagged `v0.1.0-no-collector` release is the stable catalogue-only baseline.
The collector does not download or store datasets themselves. It extracts
dataset page metadata, classifies pages with three LLM voters, finds possible
data distributions, and validates download/API links lightly.

## Structure

- `backend/app/main.py`: FastAPI app setup, CORS, startup, and router registration
- `backend/app/database.py`: compatibility facade for the async PostgreSQL DB layer
- `backend/app/db/*.py`: DB connection, schema, sources, collected datasets, jobs, and JSON serialization
- `backend/app/routes/sources.py`: `/sources` API routes for dataset page links
- `collector/`: generic collector modules for extraction, classification, validation, and discovery
- `frontend/src/App.jsx`: React UI that reads and displays dataset links
- `tests/test_database.py`: database structure and seed test
- `tests/test_collector_pipeline.py`: collector extraction, classification, and validation tests

## Documentation

- [`docs/ONBOARDING.md`](docs/ONBOARDING.md): concise developer setup and code-reading guide
- [`docs/technical-design-document.md`](docs/technical-design-document.md): current technical design
- [`docs/collector-pipeline-diagram.md`](docs/collector-pipeline-diagram.md): current runtime flows
- [`docs/classification-architecture.md`](docs/classification-architecture.md): LLM contracts, prompts, and voting
- [`docs/database-schema-diagram.md`](docs/database-schema-diagram.md): current PostgreSQL schema
- [`docs/dataset-collection-and-quality-policy.md`](docs/dataset-collection-and-quality-policy.md): draft collection and quality policy
- [`docs/roadmap.md`](docs/roadmap.md): proposed product and production work
- [`docs/multi-repository-architecture.md`](docs/multi-repository-architecture.md): proposed multi-provider search design
- [`docs/adr/0001-postgresql-only.md`](docs/adr/0001-postgresql-only.md): PostgreSQL migration decision

## Collector

Current MVP layer:

- extracts a normalized page snapshot from HTML;
- extracts normalized dataset and health evidence for LLM classification;
- accepts a page when at least two of three LLM voters accept it;
- detects known publishers, hosting platforms, and uploaders when possible;
- extracts likely CSV, XLSX, JSON, ZIP, API, and download distributions;
- ignores PDF as a dataset distribution by default;
- validates distributions with `HEAD` first, then partial `GET` fallback.
- discovers structured CKAN, Socrata, and `data.json`/DCAT catalogues first,
  then uses `robots.txt`/`sitemap.xml` as the generic website fallback before
  analyzing pages.

The collector is intentionally site-agnostic. Site-specific logic should live in
future adapters, not in the core extractor or classifier.

## Backend

Install dependencies:

```bash
cd backend
../.venv/bin/pip install -r requirements.txt
```

Start PostgreSQL locally:

```bash
export POSTGRES_PASSWORD='change-me-locally'
docker compose up -d postgres
```

Configure the API database URL:

```bash
export DATABASE_URL="postgresql://global_health:${POSTGRES_PASSWORD}@127.0.0.1:5432/global_health"
```

Configure the OpenAI classifier. All three model variables are required and
must contain distinct model names:

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_CLASSIFIER_MODEL_1="model-a"
export OPENAI_CLASSIFIER_MODEL_2="model-b"
export OPENAI_CLASSIFIER_MODEL_3="model-c"
```

The PostgreSQL database is managed by the application. It must be empty on
first startup; the backend creates the current schema, stores its version in
`schema_migrations`, and applies the default system seeds. Partial PostgreSQL
schemas or hand-modified application tables are not migrated automatically.

Run the API:

```bash
cd backend
DATABASE_URL="$DATABASE_URL" PYTHONPATH=.. ../.venv/bin/python -m uvicorn app.main:app --reload --reload-dir . --reload-dir ../collector --port 8001
```

Useful endpoints:

```txt
GET  /health
GET  /sources
POST /sources
GET  /sources/{id}/page
POST /collector/collection-jobs
GET  /collector/collection-jobs/{job_id}
GET  /collector/collected-datasets
POST /collector/search-datasets
POST /collector/search-repositories
POST /collector/classify-repository-result
```

`POST /collector/search-datasets` searches PostgreSQL first. Matching collected
datasets are returned with `origin: "database"` and do not trigger repository or
LLM calls. When there is no local match, the route returns repository candidates
with `origin: "online"`; the frontend then classifies them progressively. The
older `/collector/search-repositories` endpoint remains available for direct
online-only searches.

Only the PostgreSQL lookup uses a reduced query: the catalog-generic terms
`data`, `dataset`, and `database` are removed, while PostgreSQL's `english`
dictionary handles grammatical words and lexical variants. The original query
is preserved for API responses, DataCite, LLM classification, and display. Local
search currently targets primarily English metadata; complete bilingual search
is not implemented.

The current development schema includes a weighted PostgreSQL full-text GIN
index using the `english` configuration. No upgrade migration is provided;
recreate a local database created with an earlier version of schema 1 or with
the previous `simple` search vector.

Example:

```bash
curl -i http://127.0.0.1:8001/sources
```

Add a dataset page:

```bash
curl -i -X POST http://127.0.0.1:8001/sources \
  -H "Content-Type: application/json" \
  -d '{"source_key":"who_data_portal","name":"WHO Data","description":"WHO data portal","theme":"General","page_url":"https://platform.who.int/data"}'
```

Start an asynchronous collection job:

```bash
curl -i -X POST http://127.0.0.1:8001/collector/collection-jobs \
  -H "Content-Type: application/json" \
  -d '{"url":"https://data.humdata.org/?q=health"}'
```

Poll the collection job:

```bash
curl -i http://127.0.0.1:8001/collector/collection-jobs/1
```

Collection jobs include discovery counters such as `discovered_count`,
`analyzed_count`, `accepted_count`, `rejected_count`,
`invalid_distribution_count`, and `discovery_methods`.

List saved collected datasets:

```bash
curl -i http://127.0.0.1:8001/collector/collected-datasets
```

## Frontend

Run the React app against the backend on port `8001`:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

If `VITE_API_BASE_URL` is not set, the frontend also defaults to
`http://127.0.0.1:8001`.

Open:

```txt
http://127.0.0.1:5173/
```

The frontend supports repository search with progressive LLM classification,
source collection jobs, and inspection of saved datasets and distributions.

## Checks

```bash
.venv/bin/python -m ruff check .
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest
npm --prefix frontend run build
```

Database tests create and drop an isolated PostgreSQL schema per test. If
`TEST_DATABASE_URL` is not set, PostgreSQL-specific tests are skipped. If
`TEST_DATABASE_URL` is set but PostgreSQL is unreachable, tests fail so a broken
CI database setup cannot pass silently.
