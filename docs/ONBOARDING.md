# Developer onboarding

Use this guide to change the Python API, collector or optional React interface.
To try the API without installing development tools, follow the
[README quick start](../README.md#quick-start). HTTP contracts belong in the
[API guide](api-integration.md); infrastructure settings belong in
[deployment](DEPLOYMENT.md).

## Start locally

### Requirements and dependencies

Use Python 3.11, uv 0.12.17, Docker with Compose, and Node.js 22.12+ for frontend work
(or a newer supported LTS release).
These match the checked-in development and CI configuration. Python 3.11 is the
minimum supported version. Actual classifications need EPFL laboratory access and credentials
for all three configured RCP models. Use the keys provided through your laboratory
access. Unit tests use simulated providers and need no model credentials.

If uv is not installed, use the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
For the version used by this project, on macOS or Linux:

```sh
curl -LsSf https://astral.sh/uv/0.12.17/install.sh | sh
```

Open a new terminal if needed, then check `uv --version`. Use uv for Python
dependencies in both the main application and the optional Search Lab. The
Docker-only quick start does not require installing uv on your computer.

From the repository root:

```sh
uv sync --locked --extra dev
npm --prefix frontend ci
```

Skip npm if you only change Python. `pyproject.toml` and `uv.lock` own Python
dependencies. Normal installs use `--locked`. When changing a dependency, update
`pyproject.toml`, refresh the lock with `uv lock`, then sync and validate. Use
`uv lock --upgrade-package PACKAGE` only when deliberately upgrading that package.

### Local environment

Create the ignored `.env.local` at the repository root. Replace each credential
placeholder; choose a random database password containing only URL-safe characters
so it can also appear in `DATABASE_URL`.

```sh
export POSTGRES_PASSWORD="replace-with-a-random-local-password"
export DATABASE_URL="postgresql://global_health:${POSTGRES_PASSWORD}@127.0.0.1:5432/global_health"
export RCP_DEEPSEEK_API_KEY="replace-with-your-deepseek-credential"
export RCP_GEMMA_MEDITRON_API_KEY="replace-with-your-gemma-meditron-credential"
export RCP_APERTUS_MEDITRON_API_KEY="replace-with-your-apertus-meditron-credential"
export API_AUTH_MODE="local"
export VITE_API_AUTH_MODE="local"
export VITE_API_BASE_URL="http://127.0.0.1:8001"
```

Each voter reads its own credential variable. Obtain credentials authorized for
each configured model; the application does not substitute another voter's key.
Default model IDs are defined in `collector/classification/providers/epfl_rcp.py`;
set the corresponding `RCP_*_MODEL` variable only when overriding a default.
Never commit the populated file or put model keys or access tokens in `VITE_*`
variables: Vite exposes those values to the browser.

### Database and API

Load your environment, then start PostgreSQL:

```sh
source .env.local
docker compose -f docker-compose.local.yml up -d postgres
```

Wait for PostgreSQL to become healthy. In the same terminal, start the API:

```sh
cd backend
PYTHONPATH=.. ../.venv/bin/python -m uvicorn app.main:app \
  --reload --reload-dir . --reload-dir ../collector \
  --host 127.0.0.1 --no-proxy-headers --port 8001
```

The API applies its single initial migration to an empty database on startup.
Earlier pre-release schemas require a fresh database; startup does not convert
them. Keep one API process and instance per application database/schema; do not
add Uvicorn workers.
Local mode accepts loopback clients and the supported development origins only.
All local searches share the `local-user` owner and its quotas.

Check `http://127.0.0.1:8001/health` for liveness and `/ready` for database,
ownership, worker and model configuration readiness. Readiness does not call a
model or prove provider access. Interactive API docs are at `/docs`.
Real searches consume model quota and can save catalogue records.

### Optional React interface

In another terminal, from the repository root:

```sh
source .env.local
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/`. Local mode needs no token and works only in the
development build. For token authentication or a website served with visitor
cookies, follow [API integration](api-integration.md) and
[deployment](DEPLOYMENT.md) instead of exposing local mode.

Stop the API and frontend with Ctrl+C in their terminals. Stop the development
database with `docker compose -f docker-compose.local.yml stop postgres` from
the repository root; this preserves its data volume.

## Choose the owning module

| Change | Start here |
| --- | --- |
| Search admission, retry and ownership | `backend/app/routes/searches.py`, `backend/app/db/search_jobs.py` |
| Repository discovery and normalization | `collector/repository_search/` |
| Record-platform connector | `collector/collection/connectors/`, `collector/collection/registry.py` |
| HTML/JSON-LD extraction | `collector/extraction/` |
| Prompts, voters and classification parsing | `collector/classification/` |
| Distribution access checks | `collector/validation/downloads.py` |
| HTTP deadlines and destination policy | `collector/transport.py`, `collector/fetch.py` |
| Search, classification and collection execution | `backend/app/workers/search.py`, `classification.py`, `collection.py` |
| Worker lifecycle, state and persisted inputs | `backend/app/workers/runtime.py`, `state.py`, `jobs.py` |
| Authentication and visitor sessions | `backend/app/auth/security.py`, `backend/app/auth/sessions.py` |
| Quotas and work admission | `backend/app/quota_policy.py`, `backend/app/db/api_quotas.py` |
| API response mapping | `backend/app/routes/collector_presenters.py`, `collector_schemas.py` |
| Website search, session and catalogue state | [Optional frontend](#optional-frontend) below |

The [architecture guide](technical-design-document.md) explains module boundaries.
The [collection guide](reference/collection.md) owns extraction, validation, timeouts and
recovery rules. Keep that policy out of UI state management.

Implement database changes in the relevant `backend/app/db/` module.
`backend/app/database.py` reexports existing database functions for compatibility;
new code should import the owning `app.db` module. Similarly,
`backend/app/routes/collector.py` assembles the routers and keeps compatibility
exports; HTTP handlers belong in the topic-specific route modules above.

`backend/app/workers/` owns background execution; its `runtime.py` shares claiming,
shutdown and recovery mechanics across the three queues. `backend/app/auth/`
owns caller authentication and signed visitor sessions. Quota policy stays
separate because HTTP admission and database commands both use it.

### Follow a search through the code

1. `backend/app/routes/searches.py` records the request in PostgreSQL.
   `backend/app/workers/search.py` checks the saved catalogue, then discovers
   external candidates when needed; `backend/app/workers/classification.py`
   evaluates those candidates.
2. For an accepted candidate, `backend/app/workers/collection.py` calls
   `collect_repository_candidate_with_report` in `collector/main.py`, which
   delegates to `collect_record` in `collector/collection/orchestrator.py`.
   This resolves one record's metadata and checks its resource links.
3. `backend/app/db/collection_completion.py` stores the collection results and
   accepted datasets in PostgreSQL. Clients read the saved progress and results.

`collect_source_with_report` in `collector/main.py` is the separate bounded
source-discovery entrypoint; use the single-record path above for an already
identified repository candidate.

## Validation

Shared pytest fixtures belong in `tests/conftest.py`; reusable builders and
simulated provider responses belong in `tests/helpers/`. Import those helpers
directly instead of importing from another `test_*.py` module.

From the repository root, after installing development dependencies:

```sh
.venv/bin/ruff check .
.venv/bin/pytest tests search_lab/tests
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

### Disposable PostgreSQL for integration tests

Use a separate test database, never the application database. One local option:

```sh
docker run --name global-health-test-db --rm -d \
  -e POSTGRES_DB=global_health_test -e POSTGRES_USER=global_health_test \
  -e POSTGRES_PASSWORD=local-test-only \
  -p 127.0.0.1:55432:5432 postgres:16
docker exec global-health-test-db pg_isready -U global_health_test -d global_health_test
export TEST_DATABASE_URL="postgresql://global_health_test:local-test-only@127.0.0.1:55432/global_health_test"
.venv/bin/pytest tests search_lab/tests
```

Wait until `pg_isready` reports that it accepts connections before running tests.
Fixtures create and drop isolated schemas. Database tests skip without
`TEST_DATABASE_URL`; an unreachable configured database fails the suite.
When finished, run `docker stop global-health-test-db` and
`unset TEST_DATABASE_URL`. This disposable container and its anonymous data volume
are removed when it stops; no application volume is reused.

### Checks for the changed component

| Change | Validation |
| --- | --- |
| Public API contract | `tests/test_standalone_api_contract.py`, `tests/test_search_command_routes.py` |
| Ownership, errors or recovery | `tests/test_standalone_api_failures.py`, relevant worker/database tests |
| Process startup/restart | `tests/test_standalone_api_runtime.py`, with the disposable test database |
| Connector | Its contract fixtures; see [connector development](reference/collection-connectors.md#adding-a-connector) |
| Website lifecycle | Hook/component tests, build and browser suite below |
| Browser collection service | `npm --prefix browser ci`, then `npm --prefix browser test` |
| Laboratory | [Its own test instructions](../search_lab/README.md#test-and-remove) |

Install browser engines once before running the frontend browser suite:

```sh
cd frontend
npx playwright install --with-deps chromium firefox webkit
npm run test:browser
```

The browser harness uses isolated test servers and simulated services. The
[CI workflow](../.github/workflows/ci.yml) also defines the Python/PostgreSQL,
frontend, browser, firewall and proxy jobs. Some infrastructure or throughput
checks are opt-in locally. Report skipped checks and the tested revision;
simulated providers do not prove that real models or a deployment work.

## Optional frontend

The local React interface is an API client. Its setup is [above](#optional-react-interface);
HTTP commands, authentication, retries and progress contracts belong to
[API integration](api-integration.md). The public API-only repository excludes
this main interface; the independent [Search Lab](../search_lab/README.md) remains included.

| Module under `frontend/src/` | Responsibility |
| --- | --- |
| `App.jsx` | Search submission, restoration and navigation |
| `jobs/useSearchProgress.js` | Search snapshots, polling and downstream commands |
| `auth/useApiSession.js` | Identity, cancellation and visitor bootstrap |
| `api/client.js`, `api/commands.js` | Transport, authentication, cooldowns and command keys |
| `catalog/` | Catalogue pagination, refresh ordering and saved details |
| `hooks/useCollectionHistory.js` | Paginated collection diagnostics |

Keep server work independent of browser tracking: reading progress, opening a
card or reconnecting must not submit another job. Closing the interface does not
cancel server work. On identity changes, abort obsolete reads and discard private
state. Regression tests live beside their hooks and in `frontend/src/App.*.test.jsx`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Port 8001 occupied | Stop your old API in its terminal before starting a replacement |
| `/ready` returns 503 | Database, single-instance ownership, worker state and all three model settings |
| Every classification fails | Each `RCP_*_API_KEY` and its model access; voters do not fall back to another key |
| Search submission returns 429 | Honor `Retry-After`; keep the key for the same intended command |
| Old results after identity changes | Session cancellation and request generations |
| Schema validation fails | Follow [schema operations](DEPLOYMENT.md#schema-validation-and-retired-source-administration); do not erase data to bypass it |

Use [API response rules](api-integration.md#response-handling-for-an-independent-interface)
and [pipeline diagnostics](reference/pipeline-outcomes.md) to locate a failure.
Never include credentials, raw pages or private cookies in a shared report.

## Before submitting a change

- Keep provider behavior in providers/connectors; preserve bounded reads,
  dataset identity, TLS and destination checks.
- Keep external calls outside transactions; preserve owner filters, atomic
  admission, idempotency, durable votes and stale-write guards.
- Validate the changed component and describe skipped/limited checks.
- Update the guide that owns the changed contract and link to it elsewhere.
- Review the selected diff for local configuration/generated evidence. The
  laboratory stays optional. Maintainer priorities are in [TODO.txt](../TODO.txt).
