# Global Health Dataset Catalog

A React, FastAPI, and PostgreSQL application for discovering, classifying, validating, and cataloguing global health dataset pages.

The application stores dataset metadata and links. It does not download or retain complete dataset files.

## Overview

The project is under active development.

The current application can:

- search previously collected datasets in PostgreSQL;
- fall back to external repository search when no local result is found;
- classify repository results and dataset pages through EPFL RCP;
- discover pages from CKAN, Socrata, data.json/DCAT, and websites;
- validate candidate download and API links;
- persist accepted datasets and their distributions.

The catalogue contains seeded official sources, but the application does not yet guarantee that every collected dataset comes from an official publisher.

## Architecture

```text
React frontend
      |
      v
FastAPI backend
      |
      +-- PostgreSQL search and persistence
      +-- External repository search
      +-- Background collection jobs
      |
      v
Collector
      |
      +-- Discovery and extraction
      +-- EPFL RCP classification
      +-- Distribution validation
```

## Quick start

### Requirements

- Python 3.9 or newer
- Node.js 20 or newer
- Docker
- An EPFL RCP API key
- One private API access token of at least 32 characters

### Install Dependencies

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

### Configure the Environment

Create or update `.env.local`:

```bash
export POSTGRES_PASSWORD="change-me-locally"
export DATABASE_URL="postgresql://global_health:${POSTGRES_PASSWORD}@127.0.0.1:5432/global_health"

export RCP_API_KEY="your-rcp-api-key"
export RCP_CLASSIFIER_MODEL="deepseek-ai/DeepSeek-V4-Flash-0731"
export COLLECTION_MAX_CONCURRENCY="2"

# The JSON key is the stable owner ID; the value is that user's private token.
export API_ACCESS_TOKENS='{"local-user":"replace-with-at-least-32-random-characters"}'

export VITE_API_BASE_URL="http://127.0.0.1:8001"
```

Load the variables:

```bash
source .env.local
```

`.env.local` is ignored by Git. Never commit passwords or API keys.

### Start PostgreSQL

```bash
docker compose -f docker-compose.local.yml up -d postgres
```

### Start the Backend

```bash
cd backend
PYTHONPATH=.. ../.venv/bin/python -m uvicorn app.main:app \
  --reload \
  --reload-dir . \
  --reload-dir ../collector \
  --port 8001
```

The API is available at:

- `http://127.0.0.1:8001`
- `http://127.0.0.1:8001/docs`

### Start the Frontend

In another terminal, from the repository root:

```bash
source .env.local
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173/`.
Enter the token configured for `local-user` in the runtime **Jeton API** field.
The token is stored only in that browser tab's `sessionStorage`; it is not a
Vite build variable and must never be compiled into the frontend.

The local Compose file publishes PostgreSQL only on `127.0.0.1`. The main
`docker-compose.yml` is for HTTPS deployment behind the external Traefik and
does not publish PostgreSQL. See [Secure deployment](docs/DEPLOYMENT.md) for
the required domain, certificates, and container egress policy.

For a more detailed setup and troubleshooting guide, read
[Developer Onboarding](docs/ONBOARDING.md).

## Main workflows

Repository search and source collection are connected workflows:

```text
Repository search
    -> authenticate and consume the owner's search quota
    -> search PostgreSQL first
    -> search DataCite when no local result exists
    -> persist the owned search session and external candidates
    -> classify owned candidates by server-generated ID and quota
    -> automatically collect accepted candidates
    -> persist only datasets that pass page and distribution validation

Source collection
    -> can start from an accepted repository candidate
    -> can also start manually from a configured source
    -> dataset-page classification
    -> distribution validation
    -> PostgreSQL persistence
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check that the backend process is running |
| `POST` | `/collector/search-datasets` | Search PostgreSQL, then external repositories |
| `POST` | `/collector/repository-candidates/{candidate_id}/classify` | Classify one persisted external candidate |
| `POST` | `/collector/collection-jobs` | Start a source collection job |
| `GET` | `/collector/collection-jobs/{id}` | Read collection progress |
| `GET` | `/collector/collected-datasets` | List persisted datasets |

All routes in the table except `/health` and `/collector/collected-datasets`
require `Authorization: Bearer <token>`. `POST /sources` is protected as well.
Search and classification quotas are counted per configured owner in
PostgreSQL; optional environment overrides are documented in the TDD.

Interactive API documentation:

- Swagger UI: `http://127.0.0.1:8001/docs`
- ReDoc: `http://127.0.0.1:8001/redoc`
- OpenAPI schema: `http://127.0.0.1:8001/openapi.json`

## Project structure

```text
backend/app/                 FastAPI routes, PostgreSQL access, orchestration
collector/                   Discovery, classification, validation
frontend/src/                React interface
tests/                       Python tests
docs/                        Architecture, policy, decisions, onboarding
```

## Tests

Run the standard checks from the repository root:

```bash
.venv/bin/ruff check .
.venv/bin/pytest
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

To include PostgreSQL integration tests:

```bash
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/pytest
```

## Documentation

Start with:

1. [Developer Onboarding](docs/ONBOARDING.md)
2. [Technical Design](docs/technical-design-document.md)

Detailed documentation:

- [Collector Pipeline](docs/collector-pipeline-diagram.md)
- [Classification Architecture](docs/classification-architecture.md)
- [Database Schema](docs/database-schema-diagram.md)
- [Secure Deployment](docs/DEPLOYMENT.md)
- [Proposed Multi-Repository Architecture](docs/props/multi-repository-architecture.md)
- [Roadmap](docs/roadmap.md)
- [ADR 0001: PostgreSQL Only](docs/adr/0001-postgresql-only.md)

## Development notes

- Repository search sessions and provider candidates are persisted for trusted
  classification and auditability. Provider metadata is never inserted directly
  into `collected_datasets`: accepted candidates still pass page classification
  and distribution validation before catalogue persistence.
- Repository relevance classification does not independently guarantee health relevance.
- Source authority and licensing policies are not fully enforced.
- Dataset deduplication currently uses the normalized dataset URL.
- Background jobs are process-local. Single-process startup marks interrupted
  jobs and candidate classifications as errors, but there is no durable worker
  queue or multi-worker ownership.
- Static per-user Bearer tokens, search-session ownership, and PostgreSQL
  request quotas protect costly and mutating routes. This MVP mechanism is not
  an OAuth/OIDC login system and should be replaced by an institutional identity
  provider before broader multi-user production use.
- Production monitoring and human review workflows are not implemented.
