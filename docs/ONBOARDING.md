# Developer onboarding

Use this guide to change the Python API or collector. The optional
[Search Lab](../search_lab/README.md) has its own interface and setup.
To try the API without installing development tools, follow the
[README quick start](../README.md#quick-start). HTTP contracts belong in the
[API guide](api-integration.md); infrastructure settings belong in
[deployment](DEPLOYMENT.md).

## Start locally

### Requirements and dependencies

Use these versions to match the checked-in development and CI configuration:

- Python **3.11**, selected by `.python-version` and tested in CI. The package
  requires Python 3.11 or later; newer versions are not currently tested in CI.
- uv **0.12.17**, also used in CI and the backend image.
- Docker with a **current Compose plugin (minimum 2.3.0)**, invoked as `docker compose`.
  Legacy `docker-compose` 1.x is not supported; see the
  [quick-start version checks](../README.md#quick-start) and
  [Linux plugin installation](https://docs.docker.com/compose/install/linux/).
- Node.js **22.12 or later within 22.x**, recommended for the optional Search Lab
  interface or collection browser service. CI uses Node.js 22; the lab's
  `frontend/package.json` also declares other accepted Node.js versions.

Compose starts PostgreSQL **16**; a separate database installation is not needed.
Actual classifications need EPFL laboratory access and credentials
for all three configured RCP models. Use the keys provided through your laboratory
access. Unit tests use simulated providers and need no model credentials.

If uv is not installed, use the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/).
For the version used by this project, on macOS or Linux:

```sh
curl -LsSf https://astral.sh/uv/0.12.17/install.sh | sh
```

Open a new terminal if needed, then check `uv --version`. Use uv for Python
dependencies in both the main application and the optional Search Lab. The local quick start uses uv for the Python API and Docker for PostgreSQL.

From the repository root:

```sh
uv sync --locked --extra dev
```

`pyproject.toml` and `uv.lock` own Python dependencies; each Node.js component has
its own `package.json` and `package-lock.json`. These files record library
versions, so they are not duplicated in this guide. Normal Python installs use
`--locked`; Node.js installs use `npm ci`. When changing a Python dependency, update
`pyproject.toml`, refresh the lock with `uv lock`, then sync and validate. Use
`uv lock --upgrade-package PACKAGE` only when deliberately upgrading that package.

### Local environment and startup

Use the same setup as the [README quick start](../README.md#quick-start):

```sh
uv run --locked python scripts/setup_api.py
# Fill the three RCP_*_API_KEY values in .env.api.
uv run --locked python scripts/start_api.py
```

In another terminal:

```sh
uv run --locked python scripts/api_client.py --query "malaria"
```

The private `.env.api` is the canonical local server configuration. The launcher
loads it as literal settings, never as executable shell code. It constructs the
host-side `DATABASE_URL` from its PostgreSQL settings, starts the existing Compose
database and runs Uvicorn on loopback with one worker and proxy headers disabled.
The client loads `.env.api-client`, containing only a base URL and local mode.
`.env.local` is not loaded by these scripts; manually exported settings should be
migrated deliberately. The optional laboratory has its own configuration.

For manual Python startup, load the required environment and run from the root:

```sh
uv run --locked uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers
```

Local requests need no token or session. They must come from loopback, use a
local hostname and satisfy the existing origin/forwarding-header checks.
All local searches share the `local-user` owner and its quotas.

`/health` is a liveness check. `/ready` also checks database, runtime and model
configuration. Neither endpoint proves provider access. A real search uses
provider/model quotas and can persist catalogue records.

### Existing installations

The API accepts `API_AUTH_MODE=local` or `public`. The Python client uses
`API_CLIENT_MODE` in `.env.api-client`. For local use, select `local` and preserve
the generated API address, database password and model keys. Public deployment
uses signed anonymous sessions and the exact website origin described in
[deployment](DEPLOYMENT.md).

The single schema baseline is version 1. It creates the complete database with
local/public search access modes directly. Repeated startup validates the schema
without rewriting owners or deleting records. Earlier pre-release schemas are
unsupported; startup does not convert or erase them.

An existing Docker-only API database uses a different volume from the native
local PostgreSQL setup. Starting the launcher does not transfer that data. Keep
the old volume and password and back up/restore deliberately before changing
installations. No setup script moves or deletes database volumes.

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
| Search, classification and collection execution | `backend/app/workers/search.py`, `backend/app/workers/classification.py`, `backend/app/workers/collection.py` |
| Worker lifecycle, state and persisted inputs | `backend/app/workers/runtime.py`, `backend/app/workers/state.py`, `backend/app/workers/jobs.py` |
| Authentication and visitor sessions | `backend/app/auth/security.py`, `backend/app/auth/sessions.py` |
| Quotas and work admission | `backend/app/quota_policy.py`, `backend/app/db/api_quotas.py` |
| API response mapping | `backend/app/routes/collector_presenters.py`, `collector_schemas.py` |

The [architecture guide](technical-design-document.md) explains module boundaries.
The [collection guide](reference/collection.md) owns extraction, validation, timeouts and
recovery rules. Keep that policy out of UI state management.

Implement database changes in the relevant `backend/app/db/` module.
`backend/app/database.py` reexports existing database functions for compatibility;
new code should import the owning `app.db` module. Similarly,
`backend/app/routes/collector.py` assembles the routers and keeps compatibility
exports; HTTP handlers belong in the topic-specific route modules above.

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
| Browser session or CORS contract | `tests/test_visitor_sessions.py`, `tests/test_security.py`, `tests/test_api_cors.py` |
| Browser collection service | `npm --prefix browser ci`, then `npm --prefix browser test` |
| Laboratory | [Its own test instructions](../search_lab/README.md#test-and-remove) |

The [CI workflow](../.github/workflows/ci.yml) defines Python/PostgreSQL,
Search Lab interface, collection browser, firewall and proxy checks. Some
infrastructure or throughput checks are opt-in locally. Report skipped checks
and the tested revision; simulated providers do not prove that real models or a
deployment work. Validate real browser integration separately when connecting a
client; the [visitor session contract](reference/anonymous-visitor-sessions.md)
defines cookie and origin requirements.

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
  laboratory stays optional.
