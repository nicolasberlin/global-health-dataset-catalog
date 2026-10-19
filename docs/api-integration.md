# Standalone asynchronous API

The backend owns discovery, classification, collection, quotas and durable state.
A client submits a command and may disconnect immediately after acceptance.
Reading progress is optional and never schedules work. Any HTTP client can run
and integrate the API.

## Run API + PostgreSQL

Follow the [README quick start](../README.md#quick-start) to prepare the private
configuration, start the API and PostgreSQL in Docker, and submit your first
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
The database has one initial migration, version 1, for an empty database. Earlier
pre-release schemas are not converted automatically; use a fresh database for this
baseline. `DATABASE_MIGRATE_ON_STARTUP=false` validates an initialized version 1
schema without DDL. The explicit `app.migrate` command, including `--check`,
takes ownership and requires the API to be stopped. See
[operating contracts](DEPLOYMENT.md#schema-validation-and-retired-source-administration).

### Later: deploy the same API

The API code, Compose file and HTTP routes used locally can also run on a host.
Use a separate private environment file and database for that deployment, with
fresh database/API credentials and the host's RCP keys. Do not reuse or publish
the local test configuration. For Internet access, put the API behind an HTTPS
proxy and configure its upstream to this port. `API_BIND_ADDRESS` defaults to
loopback; change it only to the bind address appropriate for your deployment.
Do not expose PostgreSQL. Update the client's `API_BASE_URL` and `API_TOKEN` to
test the deployed API. See [deployment instructions](DEPLOYMENT.md) for the
existing EPFL environment and operational constraints, and the proxy details below
for other hosting environments.

A website's application server can call the same routes with a private API token.
A public browser client uses the visitor-session mode described below; never
bundle a shared API token or an RCP key in JavaScript sent to visitors.

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
docker compose --env-file .env.api -f docker-compose.api.yml \
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
`Retry-After` headers. Swagger's Bearer authorization applies to protected
endpoints; the enabled authentication mode is selected by the server, not by
the caller. `GET /health` is a basic process liveness check. `GET /ready` also
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

The standalone deployment uses `API_AUTH_MODE=token`. Configure
`API_ACCESS_TOKENS` as a JSON object mapping stable integration owner names to
random tokens of at least 32 characters. Send `Authorization: Bearer <token>`.
The owner is derived on the server; a request cannot choose another owner.
Rotating a token while retaining its owner name preserves access to that owner's
searches. Search and job endpoints return 404 for another owner's resources.
The dataset catalogue remains publicly readable, as in the existing API.

Set `API_CORS_ORIGINS` to a comma-separated list of exact browser origins, for
example `https://catalog.example.org,http://localhost:3000`. An empty value disables
cross-origin browser access. Allowed origins can read the `Retry-After` and
`Location` response headers for retry scheduling and accepted-resource URLs.
CORS is not needed for server-to-server calls. Keep a
shared integration token on your application server; for a public browser client,
use the existing visitor-session mode described in [deployment](DEPLOYMENT.md).
Visitor sessions also own durable searches, but an expired or lost session cannot
restore that identity. The API stores only the derived owner and quota context,
never the bearer token or session cookie in a search task.

## Submit, disconnect, restore

### Python client without the interface

`scripts/test_api.py` uses only the Python standard library (Python 3.11+).
After the [README quick start](../README.md#quick-start), the client is already
configured. Run:

```sh
python3 scripts/test_api.py --query "malaria mortality in East Africa"
```

For an API already running elsewhere, prepare a client configuration. If
`.env.api-client` already exists, edit it instead of copying over it:

```sh
cp .env.api-client.example .env.api-client
```

Edit `.env.api-client`: set `API_BASE_URL` to the running API's address and
`API_TOKEN` to the backend access token provided by its operator. If running the
standalone Docker deployment yourself, use a token **value** from
`API_ACCESS_TOKENS` in `.env.api`, not the entire JSON mapping or an RCP key.
The standalone Docker deployment always uses token authentication.
The completed client file is excluded from Git. Run the same test command above.

The default API address is `http://127.0.0.1:8001`; override it with
`--base-url` or `API_BASE_URL`, including any proxy prefix. The client checks
health and readiness, submits one keyed command, follows the entire pipeline,
then retrieves datasets in batches of 100 and the bounded search diagnostics
snapshot. It saves a JSON report to `research/api/outputs/api-test.json` (override
with `--output`). These are real searches and can consume provider/model quotas
and persist datasets on the server. No frontend process is required. The
[research files guide](../research/README.md) describes API client files. The
optional [laboratory](../search_lab/README.md) keeps its code and private
data under `search_lab/`; it is not needed for this client.

```sh
# Submit and disconnect; the server keeps processing.
python3 scripts/test_api.py --query "malaria" --no-wait
# Resume using the same authentication identity.
python3 scripts/test_api.py --search-id SEARCH_UUID
python3 scripts/test_api.py --latest
# Explicit discovery retry after an eligible failed/incomplete search.
python3 scripts/test_api.py --search-id SEARCH_UUID --retry
# Public deployment: retain the cookie file to retain ownership.
python3 scripts/test_api.py --auth public --origin https://catalog.example.org \
  --base-url https://catalog.example.org/api --query "malaria"
# Backend configured with API_AUTH_MODE=local.
python3 scripts/test_api.py --auth local --query "malaria"
```

The client automatically loads `.env.api-client` from the repository root,
regardless of the working directory; `--env-file PATH` selects another file.
It does not load the server's `.env.api` or `.env.local` files.
Settings use literal `KEY=value` lines with optional quotes and comments,
without shell evaluation or variable substitution. Supported keys are
`API_BASE_URL`, `API_TOKEN`, `API_TEST_AUTH` (default `token`) and `API_PUBLIC_ORIGIN`.
Command options override environment variables, which override file values,
which override defaults. Tokens are accepted only from the file or environment,
never as command arguments or Python source edits. Exporting `API_TOKEN` still
works and takes precedence over the file; no export is needed for file-based use.
Public mode uses the server's `API_PUBLIC_ORIGIN` value (`--origin` or the
configuration), and saves its session cookie with private permissions in
`research/api/sessions/api.cookies` (`--cookie-file` to override). This session
file is only used in public mode, not for the default local token setup. Tokens and cookies
are excluded from the JSON report. Session expiry still loses visitor ownership.

The command key is printed and saved **before** submission. After an uncertain
creation response, resend the same query with `--key SAVED_KEY` and the same
identity to avoid creating duplicate work. For an uncertain retry response,
reuse `--search-id SEARCH_UUID --retry --key SAVED_KEY`. The report records
`command_action` and `command_state` (`uncertain`, `acknowledged` or `rejected`)
so a lost response is distinguishable from an explicit rejection. Save an earlier
report before reusing its output path: each invocation atomically replaces the
report with owner-only permissions. The client does not automatically resend
failed HTTP requests; HTTP 429 reports `Retry-After`.

`--retry` admits real work when eligible and can consume provider/model quotas.
After an uncertain retry response, use the saved search UUID; `--latest` can
refer to another search created in the meantime.

`--interval` defaults to 3 seconds, `--timeout` to 900 seconds of progress
tracking, and `--http-timeout` to a 30-second deadline per HTTP request, including
status, headers and body. This standalone standard-library CLI still resolves DNS
on the calling thread; its HTTP timeout cannot interrupt a stuck OS lookup. The
server collector uses a separate bounded resolver. A tracking timeout
or Ctrl+C does not cancel server work. Exit codes: 0 for successful retrieval
(including an empty result) or accepted `--no-wait`; 1 for HTTP/network/client
errors or tracking timeout; 2 for a failed/incomplete pipeline; 130 for Ctrl+C.
Diagnostics are a bounded snapshot; use the paged endpoints below for older history.

### HTTP commands

```sh
export API_BASE_URL=http://127.0.0.1:8001
# Set API_TOKEN privately to the integration token configured on the server.
# Save this key before the request; reuse it after any uncertain network response.
export SEARCH_COMMAND_KEY="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl --fail-with-body "$API_BASE_URL/collector/searches" \
  -H "Authorization: Bearer $API_TOKEN" \
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
curl --fail-with-body "$API_BASE_URL/collector/searches/latest" \
  -H "Authorization: Bearer $API_TOKEN"
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

`Idempotency-Key` is required on search creation and discovery retry. Use a UUID
or another unique value of 1–128 characters from `A-Z a-z 0-9 . _ : -`.
Keys are scoped to the authenticated owner across all supported command types.

- Same key and same command: return the original resource's **current** state,
  without creating work or charging its admission quota again. Search command
  replays return HTTP 200. The response is not a byte-for-byte historical replay.
- Same key with another operation or payload: HTTP 409. Query leading/trailing
  whitespace is ignored when comparing creation commands.
- A genuinely new search or retry requires a new key.
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
| 400 / 422 | Correct the query, request fields or pagination bounds before resubmitting. `detail` is a string for 400 and a validation-error list for 422. |
| 401 | Correct or renew the credential for this deployment's authentication mode. Token mode also sends `WWW-Authenticate: Bearer`. |
| 403 | Check the visitor request origin, or the local-mode host/client restrictions. |
| 404 | The resource is absent or belongs to another owner; neither case reveals its existence. |
| 408 | The upload exceeded its deadline before command admission. Check the connection before resending with the same command key. |
| 409 | A command key was reused with another payload/operation, or the requested retry is ineligible. Inspect progress before choosing a new command. |
| 413 | Reduce the request body; retrying the identical body will not help. |
| 429 | Wait for the `Retry-After` number of seconds. Keep the same key if this is still the same intended command. |
| 503 | Processing, authentication configuration or quota storage is unavailable. For uncertain command responses, retain the key and check progress or replay the same command after recovery. |

An HTTP timeout does not establish whether a command committed. Do not generate
a fresh key merely because the response was lost. A tracking failure also does
not cancel work; reconnect with the same owner and search ID. Display an
incomplete outcome separately from a conclusive empty result, and keep any
returned dataset IDs available to the user.

## Explicit retries

To retry initial discovery, send an empty body (or no body) with a new key:

```sh
curl --fail-with-body -X POST \
  "$API_BASE_URL/collector/searches/$SEARCH_ID/retry" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Idempotency-Key: $RETRY_COMMAND_KEY"
```

Only asynchronous discoveries that failed, or concluded incompletely, **before
publishing candidates or local results** can start a new discovery attempt.
A command against already queued/running discovery acknowledges the existing
attempt without another quota charge. Completed discovery or published results
return 409; retry the failing downstream task instead. Search quota `retry_at`
is enforced. Successful retries retain the search ID and increment `attempt`.

Existing downstream commands accept an optional `Idempotency-Key`; integrations
should always provide one:

- `POST /collector/repository-candidates/{candidate_id}/classify?retry=true`
- `POST /collector/collection-jobs/{job_id}/retry`

Reuse that key only to resend that exact command. Successful model votes remain
available through the existing vote store. Retrying a whole search does not
reset or replay downstream work. Failed collections and completed collections with
`outcome=incomplete` or `outcome=empty` can be retried while retaining saved dataset
IDs, unless all diagnostics declare that recovery is unsupported.

Transient model failures receive bounded automatic retries, reusing valid
positive and negative votes. While waiting, `execution_status=waiting_retry`,
`outcome=null`, and `polling_required=true`; diagnostics include `retry_at`,
`attempt`, and `max_attempts`. Both explicit retry commands honor provider deadlines
and can return HTTP 429 with `Retry-After`. See [LLM recovery](reference/collection.md#model-retries-and-checkpoints).
Each claimed collection attempt has a 300-second execution budget by default.
Automatic retries start a fresh window; replaying a command or recovering the
same attempt cannot extend its deadline. Expiry produces an incomplete outcome
with `collection_budget_exhausted`, retaining saved dataset IDs. See
[attempt budgets](reference/collection.md#attempt-budget) for configuration and
[collection behavior](reference/collection.md) for extraction limits, resource
validation and paginated Socrata access.

## Restart and compatibility

Queued work survives restarts. Work interrupted while running is marked with
`processing_interrupted` and can be retried explicitly through the relevant
command. Durable votes and saved datasets remain available. Attempt tokens
prevent an old discovery from overwriting a newer retry. Temporary failures while
saving discovery results retry persistence without recalling the provider.
Repairable storage failures such as PostgreSQL `DiskFull` retain computed outcomes
in their worker slot; a failure to save a terminal error also retains that slot.
Readiness and admission return 503 while a worker is blocked by such a failure.
Repair storage before restarting if keeping the computed in-memory result matters.

Shutdown stops all consumers and gives them one shared drain budget,
`WORKER_SHUTDOWN_TIMEOUT_SECONDS=10` by default. Both Compose deployments allow
20 seconds for container shutdown. An expired drain budget or forced process stop
can lose results held only in memory; committed model votes and datasets survive.

`POST /collector/search-datasets` remains as a **deprecated asynchronous alias**
of `/collector/searches`. Its response contract changes for older synchronous
clients: a new command returns 202, a keyed replay returns 200, and the body is a
command response with `Location`/`progress_url`, rather than final `items`.
Follow progress and fetch the saved dataset IDs. The alias accepts an optional
`Idempotency-Key`; without one, each POST receives a new server-generated key and
creates a new submission. Use `/collector/searches` and a saved client key for
new integrations and network retries.
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

Use the dedicated endpoints for paged history:

| Endpoint | Entries |
| --- | --- |
| `/collector/collection-jobs/{job_id}/diagnostics` | Collection-method attempts and resource checks |
| `/collector/collection-jobs/{job_id}/classification-history` | Model attempts for the job's retry lineage |
| `/collector/repository-candidates/{candidate_id}/classification-history` | Model attempts for the owned candidate |

All use `GET`, the existing owner authentication, and `Cache-Control: no-store`.
Another owner's resource returns 404. Supply `limit=1..200` (default 100) and
`offset=0..10000` (default 0). The response includes `limit`, `offset`,
`history_truncated` and `next_offset`:

```sh
curl --fail-with-body \
  "$API_BASE_URL/collector/collection-jobs/$JOB_ID/classification-history?limit=100&offset=0" \
  -H "Authorization: Bearer $API_TOKEN"
```

Fetch `next_offset` when present. A page selects recent entries and returns them
chronologically; new entries between requests can shift offsets. At the offset
cap, `next_offset` can be null while `history_truncated` remains true. Method
pages also cap checks at 100 per method and 2000 per page, reporting
`checks_truncated` when necessary.

Method-page offsets and vote-history offsets are independent. The job diagnostics
response embeds the default first model-history page, and the aggregate search
export uses bounded default pages. Fetch older vote pages through the dedicated
classification-history endpoint. Missing or removed evidence cannot be
reconstructed. Imported snapshots may contain only a recoverable vote, without
the earlier attempts or their start times.

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

The contract suite checks the API's published authentication and response schema,
accepted versus replayed commands, followable proxy-prefixed `Location` URLs,
controlled admission errors, bounded history reads, and catalogue pagination when
new datasets are inserted between requests. The failure suites cover ownership,
durable retries, provider failures and retaining partial results. Contract and
failure checks exercise FastAPI directly through ASGI. The runtime suite starts
real Uvicorn processes and HTTP sockets against the disposable database; only
external provider transports are simulated. It verifies the real worker/vote/
extraction/validation pipeline after client disconnection, restoration after
restart, local catalogue reuse, and recovery/retry after a process dies during a
collection. These runtime checks need permission to bind local sockets and
launch child processes.

The integration client has separate local HTTP tests, with neither PostgreSQL nor
provider credentials required:

```sh
.venv/bin/python -m pytest tests/test_api_cli.py
```

Launching `scripts/test_api.py` against a normally configured API is a separate live
integration check: it can consume provider quotas and save datasets. A successful
simulated suite does not prove that an external provider is currently available,
or establish production capacity under load.
