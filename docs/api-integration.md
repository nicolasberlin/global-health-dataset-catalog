# Standalone asynchronous API

The backend owns discovery, classification, collection, quotas and durable state.
A client submits a command and may disconnect immediately after acceptance.
Reading progress is optional and never schedules work. Any HTTP client can run
and integrate the API.

## Published API

`app.main:app` exposes the eight core paths: `/health`, `/ready`, `/session`,
`/collector/searches`, `/collector/searches/latest`,
`/collector/searches/{search_id}/progress`, `/collector/searches/{search_id}/diagnostics`
and `/collector/collected-datasets/by-id`. This is the complete Python client path.
Discovery, classification and collection run automatically in the same workers.

The main web interface and its additional routes are maintained locally in the
Git-ignored `interface_web/` directory. They are not included in this repository's
API, Docker images or Python wheel. The public [Search Lab](../search_lab/README.md)
uses the core API independently.

## Run API + PostgreSQL

Follow the [README quick start](../README.md#quick-start) to prepare the private
configuration, start the native Python API and Docker PostgreSQL, and submit your first
search. It also covers stopping, resuming and troubleshooting. This guide is for
integrating a client once the API is running.

The standalone Compose project uses its own persistent database volume; it does
not import an existing catalogue. To use another PostgreSQL installation, see
the [deployment instructions](DEPLOYMENT.md).

Use **one API instance with one Uvicorn process**. Workers run inside that process.
An exclusive PostgreSQL ownership lock enforces this before migrations and restart
recovery. Stop the previous API before starting its replacement.
`SEARCH_MAX_CONCURRENCY` (default 1) controls discovery concurrency;
`SEARCH_MAX_ACTIVE` (default 100) caps queued and running asynchronous discoveries.
Classification and collection retain their separate worker and quota settings.
The single database schema baseline is version 1. It initializes an empty
database with local/public search access modes directly. Repeated startup
preserves records and owners. Earlier pre-release schemas are unsupported.
`DATABASE_MIGRATE_ON_STARTUP=false` validates an initialized version 1 schema
without DDL. The explicit `app.migrate` command, including `--check`,
takes ownership and requires the API to be stopped. See
[operating contracts](DEPLOYMENT.md#schema-validation-and-retired-source-administration).

### Later: deploy the same API

The same routes, database model and workers support local and public access.
For a public deployment, use a separate environment file and database, a stable
session signing secret and the host's RCP credentials. Do not reuse the local
configuration. Put Internet deployments behind HTTPS and configure the trusted
proxy peers. Do not expose PostgreSQL. Configure the Python client with
`API_CLIENT_MODE=public`, the API address and its exact website origin in
`.env.api-client`. The cookie file is managed automatically. See [deployment](DEPLOYMENT.md).

### Reverse proxy with a URL prefix

The main `docker-compose.yml` already starts its `ai-commons-api` service with
`--root-path /ai-commons/api`, matching its Traefik prefix removal. The standalone
`docker-compose.api.yml` uses an empty root path for direct access; apply the
override below only when placing that deployment behind a prefix-removing proxy.

If the public address is `https://catalog.example.org/api` and the proxy removes
`/api` before forwarding, also configure the ASGI root path. Removing the prefix
in Traefik alone does not configure it. When running Uvicorn directly:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 --root-path /api
```

For the standalone Compose deployment, create `docker-compose.api.proxy.yml`:

```yaml
services:
  api:
    command:
      - uvicorn
      - app.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8001"
      - --workers
      - "1"
      - --root-path
      - /api
```

Then pass both Compose files when starting or updating the API:

```sh
docker compose --env-file .env.public -f docker-compose.api.yml \
  -f docker-compose.api.proxy.yml up -d --build
```

Use the actual external prefix, for example `/ai-commons/api`, in place of `/api`.
The proxy must keep forwarding all requests for that prefix to this API. Without
a public prefix, keep the default empty root path. Client-supplied
`X-Forwarded-Prefix` is not used to build response URLs.

`Location` and `progress_url` are URL paths including this configured prefix.
Resolve them against the response URL as standard URL references; do not prepend
the configured API prefix a second time. For example,
`Location: /api/collector/searches/ID/progress` from a response at
`https://catalog.example.org/api/collector/searches` resolves to
`https://catalog.example.org/api/collector/searches/ID/progress`.

The live contract is available at `/openapi.json`, with interactive documentation
at `/docs` (both under the external prefix when configured). Search command
responses describe acceptance/replay, expected errors, and the `Location` and
`Retry-After` headers. OpenAPI describes the active anonymous cookie in public mode and no required
credential locally. The access mode is selected by the server. `GET /health` is a basic process liveness check. `GET /ready` also
checks ownership, worker health, local model settings and database availability;
503 indicates the API cannot currently accept processing work.

HTTP request bodies are bounded before parsing or admission. The default
`API_MAX_REQUEST_BODY_BYTES=65536` allows 64 KiB; accepted configuration is
1024–1048576 bytes. Oversized bodies return 413, including bodies without a
reliable `Content-Length`. This request-size guard applies independently of
workload quotas and the Traefik traffic limits.

The complete body must also arrive within `API_REQUEST_BODY_TIMEOUT_SECONDS`
(default 30; valid range 1–120 seconds). Slow or stalled bodies return 408 before
authentication or admission, with `Cache-Control: no-store`. This is one total
window, including every chunk. Clients should use a new connection after an
incomplete HTTP/1 upload times out. Headers and TLS require limits at the proxy.

Database statement or lock timeouts return a safe 503 with `Retry-After: 5` and
`Cache-Control: no-store`. Retry a mutation with its original idempotency key;
the API does not automatically repeat a command in its HTTP handler.

## Authentication and client origins

The API supports `local` (default) and `public`. Public access uses anonymous
visitor sessions. Local mode accepts only loopback clients, local hostnames and allowed
browser origins, and rejects forwarding headers. All local work belongs to
`local-user`. Use the launcher in the README; no client credential is required.

Public mode obtains a signed anonymous identity through `POST /session`. The
browser or Python client retains the cookie and sends the configured exact
`Origin` on state-changing requests. Searches, jobs and diagnostics remain
owner-scoped; the saved dataset catalogue is public. Expired/lost cookies do not
recover the original visitor identity. See [anonymous sessions](reference/anonymous-visitor-sessions.md).

Set `API_CORS_ORIGINS` to exact origins only when a separate browser origin is
needed. An empty setting disables cross-origin browser access. Same-origin
hosting is simplest. CORS does not authorize requests or replace origin checks.
The server stores the owner and quota context with work, never the session cookie.
OpenAPI describes no required credentials locally and the active cookie publicly.

## Submit, disconnect, restore

### Python client without the interface

`scripts/api_client.py` launches real searches, using only the Python standard
library (Python 3.11+). After the [README quick start](../README.md#quick-start),
the client is configured for the local API. Its entire command interface is:

```sh
python3 scripts/api_client.py --query "malaria mortality in East Africa"
python3 scripts/api_client.py --latest
# Optional: wait up to 30 minutes instead of the default 15 minutes.
python3 scripts/api_client.py --query "malaria" --timeout 1800
```

Choose exactly one of `--query` and `--latest`. A query submits a new search,
follows the pipeline, then retrieves datasets in batches of 100 and bounded
diagnostics. These are real operations that consume provider/model quotas and
can persist catalogue records. `--latest` retrieves the most recent search for
the current owner, waits if necessary, and fetches its results. It never restarts
failed work. Another search created in the meantime changes what latest means.
The script always waits for the selected search. To retrieve an older search
with another HTTP client, use its saved progress URL. Manual retry commands belong
to the separately maintained web integration and are not published by this API.

For `--query`, the client validates the returned `progress_url` and uses that
path for progress checks. It accepts only the expected progress route for the
acknowledged search, either with the configured API prefix or without it, and
adds the prefix exactly once when sending the request. External URLs and other
paths are rejected. With `--latest`, the response has no `progress_url`, so the
client builds the progress path from the validated search ID. Diagnostics and
dataset requests continue to use their documented routes.

The client loads `.env.api-client` from the repository root, regardless of its
working directory. It does not read the server's `.env.api` or `.env.local`.
Environment variables override file values, which override local defaults:

```dotenv
API_CLIENT_MODE=local
```

The address defaults to `http://127.0.0.1:8001`. Standard local setup omits
`API_PORT` from the server file and `API_BASE_URL` from the client file; only
custom ports or remote deployments need these overrides.

The installation helper preserves the configured local address and port. Local
access needs no token or cookie and only allows a loopback API address. Settings
use literal `KEY=value` lines with optional quotes and comments, without shell
evaluation or variable substitution. Unknown settings in the client file are
rejected without echoing their values.
`API_BASE_URL` and `API_PUBLIC_ORIGIN` must not contain `?` or `#`, including
empty query or fragment delimiters.

To use this Python script with a public API, configure the same client file:

```dotenv
API_BASE_URL=https://catalog.example.org/api
API_CLIENT_MODE=public
API_PUBLIC_ORIGIN=https://catalog.example.org
```

`API_PUBLIC_ORIGIN` must match the server's website origin. The client obtains
and saves a visitor cookie automatically, with private permissions, in
`research/api/sessions/api.cookies`. Preserve that cookie to retain access to
the visitor's searches; an expired or missing identity cannot access the old
owner's data. Cookies are excluded from the report. A future web interface will
call the API directly and manage its browser session; it does not run this script.
Server deployment uses `.env.public` separately; see [deployment](DEPLOYMENT.md).

The fixed report path is `research/api/outputs/search-report.json`. The report
is updated during retrieval and replaced at the next invocation; copy it manually
if it needs to be retained. Earlier `api-test.json` files are left untouched.
Only one invocation may use the shared client files at a time. The process lock
is released automatically when that client exits, including after a crash.

Before a search is submitted, its generated idempotency key, query and server/
session context are saved privately in `research/api/sessions/pending-search.json`.
If acceptance is unknown after a connection failure, run the **same `--query`**
again, with the same configuration and session: the saved key is reused to avoid
duplicate work. The client does not resend automatically within one invocation.
A different query, server or session is blocked until the uncertain request is
resolved; its recovery information is preserved. `--latest` never removes it.
A validated acceptance or explicit rejection resolves the pending request.
After acceptance, another `--query` creates a new operation with a fresh key,
even if the text is identical. Use `--latest` to retrieve accepted work instead.
The report records `command_state` (`not_submitted`, `uncertain`, `acknowledged`
or `rejected`) and `idempotency_key`; the key is not an access credential.
These recovery rules apply to requests submitted by this simplified client;
older uncertain reports can still be recovered using their saved key through
the HTTP contract below.

Progress is checked every 3 seconds. Result retrieval has a 900-second default
budget, adjustable with `--timeout`; each HTTP request has a fixed 30-second
budget covering status, headers and body. The standard-library client resolves
DNS on the calling thread, so that budget cannot interrupt a stuck OS lookup.
The server collector uses a separate bounded resolver. A retrieval timeout or
Ctrl+C does not cancel an accepted search. Messages distinguish interruption
before submission, uncertain acceptance and retrieval of a known search.
Exit codes: 0 for successful retrieval (including empty results); 1 for network,
client or timeout errors; 2 for a failed/incomplete pipeline; 130 for Ctrl+C.
Diagnostics are bounded and may omit older evidence; this API does not expose
separate history pagination routes.
See the [research files guide](../research/README.md) for report contents.

### HTTP commands

These examples target local loopback access. Public clients must first obtain a
session and attach its cookie; state-changing requests also need the exact Origin.
The Python client handles this automatically when configured with `API_CLIENT_MODE=public`.

```sh
export API_BASE_URL=http://127.0.0.1:8001
# Save this key before the request; reuse it after any uncertain network response.
export SEARCH_COMMAND_KEY="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl --fail-with-body "$API_BASE_URL/collector/searches" \
  -H "Idempotency-Key: $SEARCH_COMMAND_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"query":"malaria mortality in East Africa"}'
```

A newly admitted command returns HTTP 202 after its database transaction commits:

```json
{
  "search_id": "4ee17d71-a862-4271-bc9c-c69a72303a5e",
  "execution_status": "queued",
  "attempt": 1,
  "progress_url": "/collector/searches/4ee17d71-a862-4271-bc9c-c69a72303a5e/progress"
}
```

The response also contains `Location` and `Cache-Control: no-store`. A worker can
already have advanced the execution status by the time the response is produced.
No provider or model call runs in the admission request.

Save `search_id`. The client may now exit: the server continues the complete
pipeline. Later, follow the returned `Location` against the response URL, or
restore the owner's most recently created search through the configured API base URL:

```sh
curl --fail-with-body "$API_BASE_URL/collector/searches/latest"
```

`GET /collector/searches/{search_id}/progress` and `/searches/latest` return the
same snapshot format, including:

| Field | Meaning |
| --- | --- |
| `query`, `search_id`, `attempt` | Original query, stable search ID and discovery attempt |
| `execution_status` | `queued`, `running`, `waiting_retry`, `finished` or `failed` |
| `outcome` | `null` while active; `results`, `empty` or `incomplete` afterward |
| `polling_required` | Whether work is queued, running or waiting for an automatic retry |
| `active_stages` | Currently executing stages; queues alone are not active stages |
| `origin` | `database` or `online` after discovery; `null` before it concludes |
| `local_dataset_ids` | Local results in their saved ranking order |
| `dataset_ids` | Deduplicated local and collected dataset IDs available so far |
| `items` | Candidates, classification state and associated automatic collection |
| `warnings`, `errors` | Persisted warnings and controlled structured diagnostics |
| `created_at`, `updated_at` | Discovery-session timestamps, not downstream change timestamps |

If desired, poll every few seconds while `polling_required` is true. Polling has
no effect on execution. `outcome=incomplete` can still include usable datasets;
an empty candidate list does not by itself mean a conclusive empty result.
See [outcome rules](reference/pipeline-outcomes.md) for the full interpretation.

Retrieve full saved dataset records with repeated `ids` query parameters, in
batches of at most 100:

```sh
curl --fail-with-body "$API_BASE_URL/collector/collected-datasets/by-id?ids=42&ids=57"
```

Local results are associated with the search, not copied: these IDs resolve to
the current catalogue records. Missing associations cannot be reconstructed from
an empty candidate list. `latest` also restores queued, local,
empty and failed searches; it returns 404 only if the owner has no search.

## Idempotency and failures

`Idempotency-Key` is required on search creation. Use a UUID
or another unique value of 1–128 characters from `A-Z a-z 0-9 . _ : -`.
Keys are scoped to the authenticated owner across all supported command types.

- Same key and same command: return the original resource's **current** state,
  without creating work or charging its admission quota again. Search command
  replays return HTTP 200. The response is not a byte-for-byte historical replay.
- Same key with another operation or payload: HTTP 409. Query leading/trailing
  whitespace is ignored when comparing creation commands.
- A new search requires a new key.
- Concurrent submissions with one key create one durable command.
- HTTP 429 before acceptance means quota/capacity rejection; respect `Retry-After`.
  This transaction creates neither a task nor a receipt. HTTP 503 denotes quota
  service unavailability or unavailable runtime/worker ownership. Validation errors
  use 400/422, authentication 401, and oversized request bodies 413.
- After HTTP 202, provider, quota and processing failures appear in progress.
  They are never silently converted into a conclusive empty result.

Receipts are retained without automatic expiry by default so a late replay cannot
create a new attempt. Optional operator maintenance requires an explicit retention
and idempotency window before pruning command receipts; deletion removes the
unlimited replay guarantee for those keys. See
[retention maintenance](DEPLOYMENT.md#explicit-retention-maintenance).
A response lost
between commit and receipt delivery is safe to retry with the original key.
External calls themselves are not guaranteed exactly once across process crashes.

### Response handling for an independent interface

| HTTP status | Client action |
| --- | --- |
| 202 | Save the search ID, then follow `Location`; the server owns execution. |
| 200 on a command | The saved key has already been accepted; follow the existing search. |
| 400 / 422 | Correct the query or request fields before resubmitting. `detail` is a string for 400 and a validation-error list for 422. |
| 401 | Bootstrap or renew the public visitor session. |
| 403 | Check the visitor request origin, or the local-mode host/client restrictions. |
| 404 | The resource is absent or belongs to another owner; neither case reveals its existence. |
| 408 | The upload exceeded its deadline before command admission. Check the connection before resending with the same command key. |
| 409 | A command key was reused with another payload/operation. Inspect the original request before choosing a new command key. |
| 413 | Reduce the request body; retrying the identical body will not help. |
| 429 | Wait for the `Retry-After` number of seconds. Keep the same key if this is still the same intended command. |
| 503 | Processing, authentication configuration or quota storage is unavailable. For uncertain command responses, retain the key and check progress or replay the same command after recovery. |

An HTTP timeout does not establish whether a command committed. Do not generate
a fresh key merely because the response was lost. A tracking failure also does
not cancel work; reconnect with the same owner and search ID. Display an
incomplete outcome separately from a conclusive empty result, and keep any
returned dataset IDs available to the user.

## Automatic recovery and attempt budgets

Transient model failures receive bounded automatic retries, reusing valid
positive and negative votes. While waiting, `execution_status=waiting_retry`,
`outcome=null`, and `polling_required=true`; diagnostics include `retry_at`,
`attempt`, and `max_attempts`. See
[LLM recovery](reference/collection.md#model-retries-and-checkpoints).
Each claimed collection attempt has a 300-second execution budget by default.
Automatic retries start a fresh window; recovering the same attempt cannot extend
its deadline. Expiry produces an incomplete outcome with
`collection_budget_exhausted`, retaining saved dataset IDs. See
[attempt budgets](reference/collection.md#attempt-budget) for configuration and
[collection behavior](reference/collection.md) for extraction limits, resource
validation and paginated Socrata access.

## Restart and compatibility

Queued work survives restarts. Work interrupted while running is marked with
`processing_interrupted`. Its progress, durable votes and saved datasets remain
available; the Python client can retrieve them with `--latest`. Submit a new
search to run the pipeline again. Manual repair commands belong to the private
web integration. Attempt tokens fence stale worker completions. Temporary failures while
saving discovery results retry persistence without recalling the provider.
Repairable storage failures such as PostgreSQL `DiskFull` retain computed outcomes
in their worker slot; a failure to save a terminal error also retains that slot.
Readiness and admission return 503 while a worker is blocked by such a failure.
Repair storage before restarting if keeping the computed in-memory result matters.

Shutdown stops all consumers and gives them one shared drain budget,
`WORKER_SHUTDOWN_TIMEOUT_SECONDS=10` by default. Both Compose deployments allow
20 seconds for container shutdown. An expired drain budget or forced process stop
can lose results held only in memory; committed model votes and datasets survive.

Use `POST /collector/searches` to submit a search. Every submission requires an
`Idempotency-Key`. Save the key before sending the request and reuse it with the
same payload for network retries, so a repeated request does not create another
search. Follow `Location`/`progress_url` and fetch the saved dataset IDs when ready.
Processing continues without a connected or polling client.

`tests/test_async_searches.py` verifies admission/replay concurrency, ownership,
queue and public quotas, SQL rollback, lost commit acknowledgement, migration,
restart fencing, local result restoration, and a single-POST pipeline that reaches
saved datasets after its HTTP client closes. Tests use real isolated PostgreSQL
and simulated providers, without consuming external model quota.

## Diagnostic history

`GET /collector/searches/{search_id}/diagnostics` exports an owner-scoped, partial
snapshot of the search and its accessible classification/collection history.
Raw exception text, HTML, cookies and invalid model bodies are excluded. Model
attempts contain controlled `errors` diagnostics rather than raw technical errors.

The export embeds bounded default pages and reports truncation. Missing or
removed evidence cannot be reconstructed through this API. Imported snapshots
may contain only a recoverable vote, without earlier attempts or their start times.

## Reproduce the interface-independent checks

Use a dedicated disposable PostgreSQL database and set `TEST_DATABASE_URL` to its
connection URL before running these tests. The fixtures create and drop their own
schemas. Do not point this variable at the application database. These suites
simulate provider/model responses and do not make paid model calls:

```sh
.venv/bin/python -m pytest \
  tests/test_standalone_api_contract.py \
  tests/test_standalone_api_failures.py \
  tests/test_standalone_api_runtime.py \
  tests/test_search_command_routes.py \
  tests/test_async_searches.py \
  tests/test_diagnostic_routes.py
```

The contract suite checks the published authentication and response schemas,
accepted versus replayed commands, followable proxy-prefixed `Location` URLs,
controlled admission errors and dataset retrieval by ID. The failure suites cover
ownership, provider failures and retaining partial results. Contract and failure
checks exercise FastAPI directly through ASGI. The runtime suite starts real
Uvicorn processes and HTTP sockets against the disposable database; only external
provider transports are simulated. It verifies the worker/vote/extraction/
validation pipeline after client disconnection, restoration after restart and
local catalogue reuse. These runtime checks need permission to bind local sockets
and launch child processes.

The integration client has separate local HTTP tests, with neither PostgreSQL nor
provider credentials required:

```sh
.venv/bin/python -m pytest tests/test_api_cli.py
```

Launching `scripts/api_client.py` against a normally configured API is a separate live
integration check: it can consume provider quotas and save datasets. A successful
simulated suite does not prove that an external provider is currently available,
or establish production capacity under load.
