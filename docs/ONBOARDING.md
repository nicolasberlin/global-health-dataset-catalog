# Developer Onboarding

This guide helps a new contributor install, run, test, and safely modify the Global Health Dataset Catalog.

For detailed architectural contracts, use the documents linked from the
[README](../README.md#documentation). This guide focuses on practical development work.

## 1. What You Need to Understand First

The application has two entry points that converge on the same collection
pipeline.

### Repository Search

```text
User query
    -> PostgreSQL search
    -> external repository fallback when no local result exists
    -> persistent search session and candidates
    -> EPFL RCP relevance classification
    -> accepted candidates enter automatic collection
    -> results and collection status displayed in the frontend
```

External repository metadata is persisted as an auditable candidate, not as a
catalogue dataset. The browser classifies it by `candidate_id`; the backend
reloads the authoritative query and metadata from PostgreSQL. An accepted
candidate reaches `collected_datasets` only if the normal page-classification
and distribution-validation gates produce a valid collected dataset.

### Source Collection

```text
Configured source              Accepted repository candidate
    -> discover several pages      -> open only the candidate landing page
                    \              /
                     -> metadata extraction
                     -> EPFL RCP page classification
                     -> distribution validation
                     -> PostgreSQL persistence
```

A discovered page is persisted only when:

```text
the page classifier accepts it
AND
at least one distribution validates successfully
```

## 2. Prerequisites

Install:

- Python 3.9 or newer;
- Node.js 20 or newer;
- Docker;
- Git.

You also need an EPFL RCP API key.
Generate a separate random API access token for each developer or service that
may run searches, classifications, or collections.

## 3. Install the Project

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install
```

Confirm that the main tools are available:

```bash
.venv/bin/python --version
npm --version
docker --version
```

## 4. Configure Local Environment Variables

Create or update `.env.local` in the repository root:

```bash
export POSTGRES_PASSWORD="change-me-locally"
export DATABASE_URL="postgresql://global_health:${POSTGRES_PASSWORD}@127.0.0.1:5432/global_health"

export RCP_DEEPSEEK_API_KEY="your-rcp-api-key"
export RCP_DEEPSEEK_MODEL="deepseek-ai/DeepSeek-V4-Flash-0731"
export RCP_GEMMA_MEDITRON_API_KEY="your-separate-meditron-rcp-api-key"
export RCP_GEMMA_MEDITRON_MODEL="EPFLiGHT/Gemma-3-27B-MeditronFO"
export RCP_APERTUS_MEDITRON_API_KEY="$RCP_GEMMA_MEDITRON_API_KEY"
export RCP_APERTUS_MEDITRON_MODEL="EPFLiGHT/Apertus-70B-MeditronFO"

export API_ACCESS_TOKENS='{"local-user":"replace-with-at-least-32-random-characters"}'

# Maximum synchronous collection runs per backend process.
export COLLECTION_MAX_CONCURRENCY="2"

export VITE_API_BASE_URL="http://127.0.0.1:8001"
```

Load the file before starting the backend:

```bash
source .env.local
```

Verify that the required variables exist without printing their values:

```bash
test -n "$DATABASE_URL" && echo "DATABASE_URL loaded"
test -n "$RCP_DEEPSEEK_API_KEY" && echo "RCP_DEEPSEEK_API_KEY loaded"
test -n "$RCP_GEMMA_MEDITRON_API_KEY" && echo "RCP_GEMMA_MEDITRON_API_KEY loaded"
test -n "$RCP_APERTUS_MEDITRON_API_KEY" && echo "RCP_APERTUS_MEDITRON_API_KEY loaded"
test -n "$API_ACCESS_TOKENS" && echo "API_ACCESS_TOKENS loaded"
```

Important:

- use `RCP_DEEPSEEK_API_KEY`, not `DEEPSEEK_API_KEY`;
- keep each `API_ACCESS_TOKENS` owner ID stable and each token unique;
- restart the backend after changing an environment variable;
- never commit `.env.local`;
- never paste an API key into source code, tests, logs, or documentation.

## 5. Start the Application

### Start PostgreSQL

```bash
docker compose -f docker-compose.local.yml up -d postgres
```

Check its status:

```bash
docker compose -f docker-compose.local.yml ps
```

### Start the Backend

From the repository root:

```bash
source .env.local
cd backend

PYTHONPATH=.. ../.venv/bin/python -m uvicorn app.main:app \
  --reload \
  --reload-dir . \
  --reload-dir ../collector \
  --port 8001
```

Keep this terminal open.

The backend fails closed at startup if `API_ACCESS_TOKENS` is absent or
invalid. After starting the frontend, enter your token in **API token**. The
browser keeps it in `sessionStorage` for the current tab and sends it as a
Bearer token; do not define it as a `VITE_*` variable because Vite variables are
included in the public JavaScript bundle.

Verify the backend:

```bash
curl -i http://127.0.0.1:8001/health
```

Expected response:

```json
{"status": "ok"}
```

A successful health check only confirms that the backend process is running. It does not test EPFL RCP or every external dependency.

Local development uses loopback HTTP and the standalone local Compose file.
For remote access, use the HTTPS deployment and egress configuration in
[Secure Deployment](DEPLOYMENT.md). The main Compose file requires `PUBLIC_HOST`
and an external Traefik; it does not publish a PostgreSQL host port.

### Start the Frontend

In another terminal, from the repository root:

```bash
source .env.local
npm --prefix frontend run dev
```

Open:

```text
http://127.0.0.1:5173/
```

## 6. Verify EPFL RCP Through the Application

Use the repository search field with a query such as:

```text
malaria mortality dataset
```

When no local result exists, the application should:

1. search the configured external repository;
2. persist the search and candidate metadata;
3. submit only candidate IDs for EPFL RCP classification;
4. automatically collect accepted candidates through the normal validation gates;
5. progressively display classification and collection status.

Watch the backend terminal during this test. RCP errors are logged there.

The default factory uses three concurrent RCP voters: DeepSeek, Gemma Meditron,
and Apertus Meditron. Two positive votes out of three are required. All three
responses must be usable; a missing key, timeout or invalid response fails the
classification. Each model uses its own credential variable; the example assigns
the same key value to both Meditron variables. All three share one implementation. See
[Classification Architecture](classification-architecture.md) for the current voting contract.

## 7. Code Tour

### Frontend

Start with:

```text
frontend/src/App.jsx
frontend/src/components/RepositorySearchSection.jsx
frontend/src/components/RepositoryAcceptedCard.jsx
frontend/src/components/CollectedDatasetsSection.jsx
```

The frontend owns interface state, progressive repository classification,
automatic candidate-collection progress, and result display.

### Backend

Start with:

```text
backend/app/main.py
backend/app/security.py
backend/app/routes/collector.py
backend/app/routes/sources.py
backend/app/db/
```

Repository search persistence is implemented in
`backend/app/db/search_sessions.py` and
`backend/app/db/repository_candidates.py`. Candidate classification transitions
are atomic, owned by the authenticated search principal, and errored candidates
require an explicit retry. `backend/app/db/api_quotas.py` applies atomic
fixed-minute quotas before costly operations.

The backend owns HTTP validation, PostgreSQL access, background-job orchestration, and response mapping.

### Collector

Start with:

```text
collector/main.py
collector/discovery/
collector/classification/
collector/validation/
collector/fetch.py
```

The collector owns discovery, extraction, LLM classification, distribution validation, and protected outbound requests. It does not directly own the final PostgreSQL transaction.

## 8. Where to Make a Change

| Goal | Main location |
| --- | --- |
| Change repository search behavior | `collector/repository_search/` |
| Add a repository provider | `collector/repository_search/providers/` |
| Change page discovery | `collector/discovery/` |
| Add a discovery adapter | `collector/discovery/adapters/` |
| Change LLM prompts | `collector/classification/prompts.py` |
| Change the default LLM provider or voters | `collector/classification/factory.py` |
| Change EPFL RCP configuration | `collector/classification/providers/epfl_rcp.py` |
| Change classification validation | `page_llm_classifier.py` or `repository_llm_classifier.py` |
| Change distribution checks | `collector/validation/downloads.py` |
| Change network protections | `collector/fetch.py` |
| Change API routes | `backend/app/routes/` |
| Change persistence | `backend/app/db/` |
| Change the interface | `frontend/src/` |

Keep provider-specific behavior in provider modules. Do not place RCP-specific request logic inside the generic classifier or domain models.

## 9. Testing Strategy

### Python Unit and API Tests

```bash
.venv/bin/pytest
```

### PostgreSQL Integration Tests

```bash
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/pytest
```

PostgreSQL tests create isolated schemas. If `TEST_DATABASE_URL` is not set, those tests are skipped.

### Code Quality

```bash
.venv/bin/ruff check .
git diff --check
```

### Frontend Tests and Build

```bash
npm --prefix frontend test
npm --prefix frontend run build
```

### Before Submitting a Change

Run:

```bash
.venv/bin/ruff check .
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/pytest
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

Do not document an exact permanent number of tests. The number changes as the project evolves.

## 10. Common Problems

### Port 8001 Is Already in Use

Error:

```text
[Errno 48] Address already in use
```

Find the existing process:

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
```

Prefer stopping the old backend with `Ctrl+C` in its original terminal. Then restart it after loading `.env.local`.

### Every RCP Classification Fails

Check that the expected variable exists:

```bash
source .env.local
test -n "$RCP_DEEPSEEK_API_KEY" && echo "RCP key loaded" || echo "RCP key missing"
```

Confirm that the variable is named `RCP_DEEPSEEK_API_KEY`. A key stored under `DEEPSEEK_API_KEY` is not read by the RCP provider.

Also set `RCP_GEMMA_MEDITRON_API_KEY` and `RCP_APERTUS_MEDITRON_API_KEY`.
Check that each key can access its model on the same EPFL RCP endpoint. Model names
can be overridden using `RCP_GEMMA_MEDITRON_MODEL` and
`RCP_APERTUS_MEDITRON_MODEL`. Neither Meditron voter falls back to the DeepSeek key.

Restart the backend after correcting the file.

Typical meanings:

- HTTP 400: unsupported request field, invalid payload, or invalid model name;
- HTTP 401 from FastAPI: missing or invalid application Bearer token;
- HTTP 429 from FastAPI: the owner's application quota is exhausted; respect
  the `Retry-After` header;
- HTTP 401 or 403 logged from RCP: invalid RCP key or missing RCP permission;
- HTTP 404: incorrect endpoint or unavailable model;
- timeout: RCP or network did not respond within the configured limit;
- invalid JSON: the model response did not satisfy the classification contract.

Never include the API key when sharing an error message.

### PostgreSQL Does Not Start

Check:

```bash
docker compose -f docker-compose.local.yml ps
docker compose -f docker-compose.local.yml logs postgres
```

Confirm that `DATABASE_URL` uses the same password as `POSTGRES_PASSWORD`.

### The Database Schema Is Rejected

The application initializes an empty PostgreSQL database automatically. It does not repair arbitrary partial or obsolete schemas.

The current pre-release baseline includes owned `search_sessions`,
`repository_candidates`, `api_rate_limits`, and candidate-linked
`collection_jobs`. No upgrade migration is provided for an older local schema;
recreate the local database.

For migration decisions, consult:

- [Database Schema](database-schema-diagram.md)
- [ADR 0001](adr/0001-postgresql-only.md)

Do not delete or recreate a database containing important data without explicit approval.

### Frontend Changes Do Not Appear

Confirm that the frontend development server is running and reload the page. If the API address changed, restart the frontend after updating `VITE_API_BASE_URL`.

## 11. Development Rules

When changing the project:

1. Identify the owning module before editing.
2. Add or update tests with the implementation.
3. Keep secrets outside the repository.
4. Preserve bounded network reads and URL safety checks.
5. Do not silently convert provider failures into accepted or rejected datasets.
6. Update the source-of-truth technical document when a contract changes.
7. Link to technical documentation instead of copying it into multiple files.

## 12. Recommended Reading Order

For a new contributor:

1. `README.md`
2. `frontend/src/App.jsx`
3. `backend/app/routes/collector.py`
4. `collector/main.py`
5. `collector/repository_search/service.py`
6. `collector/classification/factory.py`
7. `collector/classification/prompts.py`
8. `collector/validation/downloads.py`
9. `backend/app/db/collection_completion.py`
10. tests related to the component being changed

For detailed behavior:

- [Technical Design](technical-design-document.md)
- [Collector Pipeline](collector-pipeline-diagram.md)
- [Classification Architecture](classification-architecture.md)
- [Database Schema](database-schema-diagram.md)
- [Roadmap](roadmap.md)

## 13. Mental Model to Keep

```text
Repository search
    = authenticate a configured owner and consume a search quota
    + search PostgreSQL first
    + find external candidates when no local result exists
    + persist the owned search and candidates
    + authorize and classify trusted server-side metadata by candidate ID
    + reserve a candidate-linked collection job for accepted candidates

Automatic collection in the website
    = process one accepted repository candidate
    + accept eligible datasets
    + validate distributions
    + persist results
```

When unsure where behavior belongs, find the document or module that owns the contract instead of duplicating the rule elsewhere.
