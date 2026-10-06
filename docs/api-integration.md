# Standalone asynchronous API

The backend owns discovery, classification, collection, quotas and durable state.
A client submits a command and may disconnect immediately after acceptance.
Reading progress is optional and never schedules work. React, Node.js and the
existing frontend are not needed to run or integrate the API.

## Run API + PostgreSQL

From a checkout of this repository:

```sh
cp .env.api.example .env.api
# Edit .env.api: database password, API token, and the three model credentials.
docker compose --env-file .env.api -f docker-compose.api.yml up -d --build
```

This separate Compose project builds only the backend, starts PostgreSQL with a
persistent volume, and exposes `http://127.0.0.1:8001`. No external proxy network
is required. It uses its own database volume; it does not import an existing
catalogue automatically. For an existing PostgreSQL installation, run the backend
with its `DATABASE_URL` using the [deployment instructions](DEPLOYMENT.md).

Use **one API instance with one Uvicorn process**. Workers run inside that process.
`SEARCH_MAX_CONCURRENCY` (default 1) controls discovery concurrency;
`SEARCH_MAX_ACTIVE` (default 100) caps queued and running asynchronous discoveries.
Classification and collection retain their separate worker and quota settings.
Schema migrations through version 9 run at startup and preserve historical records and votes.

For remote access, put the API behind your HTTPS proxy and configure its upstream
to this port. `API_BIND_ADDRESS` defaults to loopback; change it only to the bind
address appropriate for your deployment. Do not expose PostgreSQL.

The live contract is available at `/openapi.json`, with interactive documentation
at `/docs`. `GET /health` is a basic process liveness check.

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
cross-origin browser access. CORS is not needed for server-to-server calls. Keep a
shared integration token on your application server; for a public browser client,
use the existing visitor-session mode described in [deployment](DEPLOYMENT.md).
Visitor sessions also own durable searches, but an expired or lost session cannot
restore that identity. The API stores only the derived owner and quota context,
never the bearer token or session cookie in a search task.

## Submit, disconnect, restore

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
pipeline. Later, read the returned path against the same API base URL (including
any proxy prefix), or restore the owner's most recently created search:

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
See [outcome rules](pipeline-outcomes.md) for the full interpretation.

Retrieve full saved dataset records with repeated `ids` query parameters, in
batches of at most 100:

```sh
curl --fail-with-body "$API_BASE_URL/collector/collected-datasets/by-id?ids=42&ids=57"
```

Local results are associated with the search, not copied: these IDs resolve to
the current catalogue records. Historical searches made before this migration
have no reconstructible local associations. `latest` also restores queued, local,
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
  service unavailability. Validation errors use 400/422, authentication 401.
- After HTTP 202, provider, quota and processing failures appear in progress.
  They are never silently converted into a conclusive empty result.

Receipts are retained without automatic expiry so a late replay cannot create a
new attempt. Deleting receipts manually removes that guarantee. A response lost
between commit and receipt delivery is safe to retry with the original key.
External calls themselves are not guaranteed exactly once across process crashes.

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
`outcome=incomplete` can be retried while retaining their saved dataset IDs.

Transient model failures now receive bounded automatic retries, reusing valid
positive and negative votes. While waiting, `execution_status=waiting_retry`,
`outcome=null`, and `polling_required=true`; diagnostics include `retry_at`,
`attempt`, and `max_attempts`. Both explicit retry commands honor provider deadlines
and can return HTTP 429 with `Retry-After`. See [LLM recovery](llm-recovery.md).
The existing frontend remains unchanged; client integration is a separate step.

## Restart and compatibility

Queued work survives restarts. Work interrupted while running is marked with
`processing_interrupted` and can be retried explicitly through the relevant
command. Durable votes and saved datasets remain available. Attempt tokens
prevent an old discovery from overwriting a newer retry. Temporary failures while
saving discovery results retry persistence without recalling the provider.

`POST /collector/search-datasets` remains available with its synchronous discovery
response for the existing frontend. It shares normalization and candidate
preparation with the worker. New integrations should use `/collector/searches`.
The frontend does not need to be installed, built, open or polling.

`tests/test_async_searches.py` verifies admission/replay concurrency, ownership,
queue and public quotas, SQL rollback, lost commit acknowledgement, migration,
restart fencing, local result restoration, and a single-POST pipeline that reaches
saved datasets after its HTTP client closes. Tests use real isolated PostgreSQL
and simulated providers, without consuming external model quota.
