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

The application does not yet guarantee that every collected dataset comes from an official publisher.

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

- Python 3.11 recommended (Python 3.9 compatibility is tested in CI)
- uv 0.12.17 ([installation](https://docs.astral.sh/uv/getting-started/installation/))
- Node.js 22 recommended
- Docker
- An EPFL RCP API key
- One private API access token of at least 32 characters

### Install Dependencies

From the repository root:

```bash
uv sync --locked --extra dev
npm --prefix frontend ci
```

`pyproject.toml` is the single source for Python dependencies, including the API
server and development tools. Commit `uv.lock` when dependencies change; local
setup, CI, and the backend image all consume this lock. `.python-version` selects
Python 3.11 by default. To check the minimum supported version, use
`uv sync --locked --extra dev --python 3.9` in a separate environment.

To update dependencies intentionally, run `uv lock --upgrade`, then
`uv sync --locked --extra dev` and the checks below. Normal installs must use
`--locked`; do not maintain a second requirements list. Use uv 0.12.17, matching
CI and Docker. This locks Python packages, not the operating-system image or apt
packages used by Docker.

### Configure the Environment

Create or update `.env.local`:

```bash
export POSTGRES_PASSWORD="change-me-locally"
export DATABASE_URL="postgresql://global_health:${POSTGRES_PASSWORD}@127.0.0.1:5432/global_health"

export RCP_DEEPSEEK_API_KEY="your-rcp-api-key"
export RCP_DEEPSEEK_MODEL="deepseek-ai/DeepSeek-V4-Flash-0731"
export RCP_GEMMA_MEDITRON_API_KEY="your-separate-meditron-rcp-api-key"
export RCP_GEMMA_MEDITRON_MODEL="EPFLiGHT/Gemma-3-27B-MeditronFO"
export RCP_APERTUS_MEDITRON_API_KEY="$RCP_GEMMA_MEDITRON_API_KEY"
export RCP_APERTUS_MEDITRON_MODEL="EPFLiGHT/Apertus-70B-MeditronFO"
export COLLECTION_MAX_CONCURRENCY="2"
export CLASSIFICATION_MAX_CONCURRENCY="2"

# Local development: no token entry, backend bound to loopback only.
export API_AUTH_MODE="local"
export VITE_API_AUTH_MODE="local"

export VITE_API_BASE_URL="http://127.0.0.1:8001"
```

Load the variables:

```bash
source .env.local
```

`.env.local` is ignored by Git. Never commit passwords or API keys.

Page and repository classification each call three models in parallel: DeepSeek,
Gemma Meditron, and Apertus Meditron. Acceptance requires two positive votes and
three usable responses. Validated responses are saved individually in PostgreSQL
by backend workers. If a model fails, an explicit retry calls only missing or
failed voters; successful negative votes are preserved too. A changed input,
model, or prompt starts a new set of votes. Each model has its own model and credential variables;
the example explicitly reuses the Gemma key for Apertus. All three use the same
client, prompt per flow, parser, and error handling. The EPFL RCP Chat Completions
endpoint, which must serve these model IDs and support the JSON response mode.
An initial classification makes three inference requests; existing
request quotas still count application operations, not individual model calls.

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
  --host 127.0.0.1 --no-proxy-headers \
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
Local mode opens directly without a token. Run the backend on `127.0.0.1`
with `--no-proxy-headers`; local access rejects remote clients and foreign browser
origins. All local searches belong to `local-user`, with quotas still enforced.
The frontend local mode applies only to the development server.

Public deployments retain the default `API_AUTH_MODE=token` and require
`API_ACCESS_TOKENS` (a JSON mapping of owner IDs to private tokens).
Never enable local mode behind a public reverse proxy.
The token is stored only in that browser tab's `sessionStorage`; it is not a
Vite build variable and must never be compiled into the frontend.

The backend also implements an opt-in `API_AUTH_MODE=public` visitor-session
foundation with per-visitor/IP quotas and global workload limits. It is not
enabled in Compose or connected to the frontend yet; HTTPS, trusted proxy
configuration, and general traffic limiting remain deployment prerequisites. See
[Anonymous visitor sessions](docs/anonymous-visitor-sessions.md) for the API
contract, configuration, and validation of the backend implementation.

The local Compose file publishes PostgreSQL only on `127.0.0.1`. The main
`docker-compose.yml` is for internal EPFL HTTP deployment on port 1312 behind the external Traefik and
does not publish PostgreSQL. See [Deployment on EPFL](docs/DEPLOYMENT.md) for
the required domain, certificates, and container egress policy.

For a more detailed setup and troubleshooting guide, read
[Developer Onboarding](docs/ONBOARDING.md).

## Main workflows

Repository search and automatic candidate collection are connected workflows:

```text
Repository search
    -> authenticate and consume the owner's search quota
    -> search PostgreSQL first
    -> search DataCite when no local result exists
    -> persist the owned search session and external candidates
    -> classify owned candidates by server-generated ID and quota
    -> automatically collect accepted candidates
    -> persist only datasets that pass page and distribution validation

Automatic collection
    -> starts from an accepted repository candidate
    -> dataset-page classification
    -> distribution validation
    -> PostgreSQL persistence
```

## API

The website offers Search and Catalog views. Source administration (`/sources`)
and the manual `POST /collector/collection-jobs` endpoint have been removed.
Automatic collection, progress, and explicit failed-job retries remain available.
Historical source records and collected datasets are preserved; startup no longer
seeds source records.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check that the backend process is running |
| `POST` | `/collector/search-datasets` | Search PostgreSQL, then external repositories |
| `POST` | `/collector/repository-candidates/{candidate_id}/classify` | Queue an owned classification (202); read its state separately |
| `GET` | `/collector/collection-jobs/{id}` | Read collection progress |
| `POST` | `/collector/collection-jobs/{job_id}/retry` | Retry an owned failed collection, preserving saved votes |
| `GET` | `/collector/collected-datasets` | List persisted datasets |

All routes in the table except `/health` and `/collector/collected-datasets`
require `Authorization: Bearer <token>`.
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
uv sync --locked --extra dev
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

GitHub Actions runs these checks on pushes and pull requests: Python 3.9 and
3.11 with a disposable PostgreSQL 16 service, frontend tests and build on Node.js
22, and a separate backend image/firewall test. The database jobs always set
`TEST_DATABASE_URL`; missing or unreachable PostgreSQL must fail CI. The Docker
firewall test also exercises public HTTPS and needs network access, but no RCP
credentials or production database.

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
- [Collection Workflow Policy — target behavior and acceptance scenarios](docs/collection-workflow-policy.md)
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
- Collection jobs use PostgreSQL as their persistent queue. Pending jobs survive
  restart; interrupted running jobs become errors. Acceptance and collection
  reservation commit together, and repeating a classification only reads its
  existing follow-up. Run a single API process/instance: there are no worker
  leases. Classification requests also persist in PostgreSQL before a bounded
  worker executes them. The frontend restores the last repository analysis.
  See the [deployment constraints](docs/DEPLOYMENT.md#collection-execution).
- Static per-user Bearer tokens, search-session ownership, and PostgreSQL
  request quotas protect costly and mutating routes. This MVP mechanism is not
  an OAuth/OIDC login system and should be replaced by an institutional identity
  provider before broader multi-user production use.
- Production monitoring and human review workflows are not implemented.
