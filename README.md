# Global Health Dataset Catalog

Small React + FastAPI app for cataloging official health dataset pages.

The tagged `v0.1.0-no-collector` release is the stable catalogue-only baseline.
The `collector-update` branch introduces the first generic collector modules.
The collector does not download or store datasets themselves. It extracts
dataset page metadata, scores whether pages are datasets and health-related,
finds possible data distributions, and validates download/API links lightly.

## Structure

- `backend/app/main.py`: FastAPI app setup, CORS, startup, and router registration
- `backend/app/database.py`: compatibility facade for the async PostgreSQL DB layer
- `backend/app/db_*.py`: DB connection, schema, sources, collected datasets, jobs, and JSON serialization
- `backend/app/routes/sources.py`: `/sources` API routes for dataset page links
- `collector/`: generic collector modules for extraction, classification, validation, and discovery
- `frontend/src/App.jsx`: React UI that reads and displays dataset links
- `tests/test_database.py`: database structure and seed test
- `tests/test_collector_pipeline.py`: collector extraction, classification, and validation tests

## Collector

Current MVP layer:

- extracts a normalized page snapshot from HTML;
- detects Schema.org `Dataset` and deterministic dataset signals;
- scores health relevance separately from dataset detection;
- detects known publishers, hosting platforms, and uploaders when possible;
- extracts likely CSV, XLSX, JSON, ZIP, API, and download distributions;
- ignores PDF as a dataset distribution by default;
- validates distributions with `HEAD` first, then partial `GET` fallback.
- discovers structured CKAN, Socrata, and `data.json`/DCAT catalogues first,
  then uses `robots.txt`/`sitemap.xml` as the generic website fallback before
  analyzing pages.

The collector is intentionally site-agnostic. Site-specific logic should live in
future adapters, not in the core extractor or classifier.

Analyze pasted HTML through the API:

```bash
curl -i -X POST http://127.0.0.1:8001/collector/analyze-html \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.org/data/catalog","html":"<html><head><title>Mortality dataset</title></head><body><h1>Mortality health dataset</h1><a href=\"https://example.org/files/mortality.csv\">Download CSV</a></body></html>"}'
```

Analyze a public URL directly:

```bash
curl -i -X POST http://127.0.0.1:8001/collector/analyze-url \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.org/data/catalog"}'
```

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

The PostgreSQL database is managed by the application. It must be empty on
first startup; the backend creates schema version 1, stores it in
`schema_migrations`, and applies the default system seeds. Existing SQLite data,
partial PostgreSQL schemas, or hand-modified application tables are not migrated
automatically.

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
POST /collector/analyze-html
POST /collector/analyze-url
POST /collector/discover-url
POST /collector/collect-url
POST /collector/collection-jobs
GET  /collector/collection-jobs/{job_id}
GET  /collector/collected-datasets
```

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

Collect, classify, validate, and save synchronously from a source URL:

```bash
curl -i -X POST http://127.0.0.1:8001/collector/collect-url \
  -H "Content-Type: application/json" \
  -d '{"url":"https://data.humdata.org/?q=health"}'
```

Run the same collection without saving:

```bash
curl -i -X POST http://127.0.0.1:8001/collector/collect-url \
  -H "Content-Type: application/json" \
  -d '{"url":"https://data.humdata.org/?q=health","save":false}'
```

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

The frontend includes a "Test collector" panel where you can paste HTML or enter
a public URL, then inspect dataset/health scores plus detected distributions.

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
