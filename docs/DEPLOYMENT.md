# Deployment and operations

For a first local run, start with the [README](../README.md). This guide covers
proxy deployment, worker lifecycle, monitoring, migrations and maintenance.
Use HTTPS for deployments outside the internal EPFL environment described below.
Module responsibilities are explained in the
[architecture guide](technical-design-document.md).

Use Docker with a current Compose plugin, **minimum 2.3.0** (`docker compose`). Legacy
`docker-compose` 1.x is not supported. See the [quick-start version checks](../README.md#quick-start)
and the [Linux plugin installation guide](https://docs.docker.com/compose/install/linux/).

## Internal EPFL deployment

The main `docker-compose.yml` targets an existing Traefik on the external
`traefik` network. The reference internal deployment uses HTTP on external port 1312,
without TLS or HTTPS redirection. It does not publish database or API ports.
HTTP is the intended mode for this EPFL-internal deployment; no migration to
HTTPS is planned. HTTPS support remains available for other hosting environments.
For a Python backend running on your laptop, use `docker-compose.local.yml`
instead; its database port is bound only to `127.0.0.1`.

Invalid request-body, migration, shutdown or collection-duration settings stop
startup. Recreate affected containers after changing environment settings or
proxy labels; editing an environment file does not change a running process.

## Use the existing external Traefik

The existing `web` entrypoint must receive traffic from host port 1312.
[The example static configuration](../deploy/traefik.example.yml) listens on
container port 80, which requires a `1312:80` port mapping on the external
Traefik container. Preserve the existing mapping if HTTP already reaches
Traefik successfully. The application Compose file does not start or reconfigure
that external Traefik.

Do not modify the shared Traefik configuration or attach the application to
unrelated production networks. The application uses labels and the external `traefik`
network specified by the infrastructure administrator. Declaring a network
external does not attach Traefik to it: verify both sides are already connected.
If they are not, ask the administrator to confirm the intended network.
No certificate resolver or port 443 is required for this internal HTTP deployment.

### Anonymous search on internal HTTP

Configure the [internal EPFL HTTP session option](reference/anonymous-visitor-sessions.md#internal-epfl-http-access)
before rebuilding the app. It is disabled by default. The API base path is
`/ai-commons/api`; configure the exact external origin, for example
`http://catalog.example.org:1312`, without a path. Replace the example hostname
with your deployment's hostname. Public mode uses anonymous sessions.

Before deployment, inspect only the network information (no credentials):

```sh
docker network inspect traefik --format '{{range .Containers}}{{println .Name .IPv4Address}}{{end}}'
```

Confirm that Traefik and the application share this network. Set
`FORWARDED_ALLOW_IPS` to the verified Traefik peer IP(s) as seen by Uvicorn.
Do not set it to `*` or trust an entire shared network. The default trusts only
loopback, so an unconfigured proxy is counted as one client and visitors may
share its quota. Recheck the peer address if Traefik is recreated. These values
cannot be inferred from the repository or certified by local browser tests.
Uvicorn handles the trusted forwarding headers; application code never trusts
an arbitrary `X-Forwarded-For` header directly.

After verifying the current proxy address, add it to the server's private `.env`:

```dotenv
FORWARDED_ALLOW_IPS=<verified-proxy-address>
```

Use the single address, not the `/16` network: other containers also share this
network. A container address can change when it is recreated. Verify that Uvicorn
receives the expected client address after deployment. The repository keeps its conservative loopback default;
the server environment must supply the deployment-specific value.

The commands below use the main `docker-compose.yml`, which automatically reads
`.env` in the repository root. Create a private **server-specific `.env`** with
`POSTGRES_PASSWORD` and all three `RCP_*_API_KEY` credentials. Keep the password
compatible with any existing database volume. Local `.env.api` and `.env.local`
are not automatically loaded by these commands; keep server credentials and data
separate from local tests.

Both API container templates explicitly select public anonymous sessions. Set
`API_SESSION_SECRET` and `API_PUBLIC_ORIGIN`; the main Compose deployment also
requires the [internal HTTP opt-in](reference/anonymous-visitor-sessions.md#internal-epfl-http-access)
for its existing HTTP infrastructure. Internet hosting requires HTTPS instead.
The `.env.public.example` template can be copied to a private server file. Generate
a stable secret once (for example `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`).
Keep it private and stable across restarts. Preserve any existing database password.

For the standalone public container:

```sh
docker compose --env-file .env.public -f docker-compose.api.yml up -d --build
```

It publishes the API to host loopback by default. A public rollout must provide
HTTPS and a correctly configured trusted proxy. Do not turn on insecure HTTP
sessions for Internet visitors. Both Compose templates forward all seven public
quota settings from the configuration. For personal use choose the native local
launcher, not public cookies or a relaxed local IP check in Docker.

Set the deployment-specific hostname and optional network exclusions:

```bash
export PUBLIC_HOST="catalog.example.org"  # replace with your hostname, without scheme/port/path
# Optional: public CIDRs routed to internal/admin services in your infrastructure.
# Comma-separated, strict IPv4/IPv6 CIDRs; DNS and PostgreSQL exceptions take precedence.
export EGRESS_BLOCKED_CIDRS=""
docker compose config --quiet
docker compose up -d --build
```

Open `http://<your-hostname>:1312/ai-commons/api/docs`.
The API router uses `web` and the configured `Host` rule. Requests under
`/ai-commons/api` reach the API on port 8001.
There is no TLS, HSTS, or HTTPS redirect middleware in this deployment.

### API prefix behind Traefik

The main Compose file starts `ai-commons-api` with
`--root-path /ai-commons/api`, matching the prefix removed by Traefik. Keep both
values aligned when changing the public API path. This makes `Location`,
`progress_url`, Swagger and OpenAPI URLs include the external prefix; a client
can follow a returned URL without adding the prefix again. Configure independent
clients to use that same external API path.

The standalone API at `http://127.0.0.1:8001` keeps an empty root path by default.
For a different proxy deployment, follow the explicit
[root-path configuration](api-integration.md#reverse-proxy-with-a-url-prefix).
Client-supplied `X-Forwarded-Prefix` does not configure this value.

## Collection execution

Verify CI results for the exact revision being deployed. Repository tests do not
establish which revision is running or verify the external proxy configuration.

Run exactly one API process and one API instance against the database. The image
explicitly starts Uvicorn with `--workers 1`. Do not scale replicas or overlap old
and new API instances during a deployment. An exclusive PostgreSQL session lock,
scoped to the database/schema, is acquired on a dedicated connection before the
pool opens, migrations run or interrupted tasks are recovered. A second instance
fails startup before it can invalidate the owner's jobs. Stop the old instance
before starting its replacement. Worker leases and multi-instance recovery are
not implemented.

The lock connection has a bounded heartbeat. Ownership loss marks the API
unavailable, stops consumers and fences further worker persistence. New mutating
HTTP requests return 503 with `Retry-After: 5`. The process does not automatically
reacquire ownership: repair the cause, stop the old process and start one instance.
Normal shutdown closes the pool before releasing the ownership connection.
Read endpoints can remain available while their underlying storage permits it.

After schema validation, the lock holder activates a new UUID in the schema's
singleton `application_ownership` row. Every queue claim, including receipt
replay, holds a shared lock on that generation until its transaction ends. A
replacement waits for earlier claims, changes the generation, recovers parent
attempts, then closes interrupted votes. An old process cannot claim work after
that handoff even if its heartbeat has not yet noticed a lost connection. Running
the migration command alone does not rotate the active generation.

`collection_jobs` is the persistent collection queue; no additional broker is
required. After startup recovery, backend consumers poll committed `pending`
jobs. `COLLECTION_MAX_CONCURRENCY` (default `2`) bounds concurrent collection
runs inside this single process; it is not the number of API processes. Each
consumer claims one job atomically only when its execution slot is available.

If PostgreSQL becomes unavailable during finalization, the consumer retains its
slot and the computed result (or execution error) in memory until its terminal
write can finish. It retries only persistence, with exponential backoff and jitter
up to 30 seconds; it does not repeat HTTP collection or LLM execution. Temporary
connection, pool, serialization, and deadlock failures are retryable. Repairable
storage failures, including PostgreSQL `DiskFull`, retain the result and retry
after backoff until repaired. If a terminal error cannot be persisted, its slot
also remains occupied instead of abandoning the attempt and claiming another
job. Storage-blocked or failed consumers make readiness and new admission return
503. Repair storage before restarting if the computed in-memory result must be
preserved. Finalization is guarded by the claim's exact
`updated_at`, which progress writes leave unchanged. A lost commit acknowledgement
cannot duplicate finalization or overwrite a newer explicitly retried attempt.

Acquisition also retries transient SQL failures, using one internal UUID per
consumer acquisition. The task transition and its `worker_claims` receipt commit
together. After a lost commit acknowledgement,
the same token retrieves the same running attempt without changing its deadline
or spending another admission. An obsolete receipt cannot acquire another task.
This applies to discovery, repository classification and collection. Empty polls
do not create receipts; one small row is retained per acquired attempt. These
receipts have no automatic expiry by default, like API command receipts. Explicit
[retention maintenance](#explicit-retention-maintenance) can prune eligible old
receipts under an operator-selected policy. They are internal and
do not replace the single-process recovery policy or guarantee exactly-once
external calls after a process crash.

- Pending jobs survive restart and are picked up automatically.
- Jobs left running by an interrupted process become errors with
  `processing_interrupted` at the next startup; they need an explicit retry.
- Normal application shutdown stops taking new work in all three queues and
  shares one `WORKER_SHUTDOWN_TIMEOUT_SECONDS` drain deadline (default 10 seconds;
  positive finite values up to 300). Both backend Compose deployments set
  `stop_grace_period: 20s`. Keep the container allowance above the drain budget
  plus process cleanup. At expiry, persistence bridges are fenced and remaining
  attempts are left for restart recovery. A synchronous call already running
  cannot be killed, but its daemon thread does not hold process exit indefinitely.
  Deadline expiry or forced termination loses in-memory outcomes; committed
  datasets and valid positive or negative model votes survive.
- A repeated classification reads its existing collection, including an empty
  or failed result. The separately maintained manual collection retry explicitly
  requeues an owned failed, incomplete or eligible empty job and consumes the
  existing classification quota. Jobs with no supported recovery are rejected.

Classification decisions and initial collection reservations share one
transaction. If reservation fails, the decision rolls back too. Temporary database
failures retry finalization. Processing failures are recorded durably; bounded
automatic model recovery or an explicit retry reuses already persisted valid
votes. A failure of that terminal write retains the slot until persistence can
complete or shutdown expires. LLM and network calls stay outside
the transaction. Classification requests persist as `queued` on existing candidates before
HTTP 202 is returned. `pending` means discovered but not requested; workers never
execute it. `CLASSIFICATION_MAX_CONCURRENCY` (default `2`) bounds the separate
classification pool. Queued requests survive restart; interrupted `classifying`
candidates become errors and require an explicit `retry=true` request. An LLM
response lost before persistence may need another call. See
[bounded model recovery](#bounded-model-recovery) for automatic retry limits.
All three queues share the same bounded consumer implementation.

Each valid voter response is committed before waiting for the remaining voters.
A changed input or ensemble configuration starts a separate classification run.
Startup marks interrupted votes as failed without discarding completed votes.
The CLI has no persistent vote store; this recovery applies to backend workers.

Clients must use `POST /collector/searches` with an `Idempotency-Key` and follow
the asynchronous command/progress contract. An accepted search continues after
client disconnection. See
[API compatibility](api-integration.md#restart-and-compatibility) before deploying
changes alongside an existing client.

### Bounded model recovery

The default policy allows three total transient attempts, two for invalid
responses, and a 120-second window for starting automatic retries. Compose
forwards `LLM_MAX_ATTEMPTS`, `LLM_INVALID_MAX_ATTEMPTS` and
`LLM_RETRY_WINDOW_SECONDS`. Set both attempt limits to 1 to disable automatic model
retries. Provider `Retry-After`, attempt limits and the retry-planning window are
independent of the collection execution budget. See the
[collection reference](reference/collection.md) for scheduling and recovery rules.

### Collection execution budget

`COLLECTION_MAX_DURATION_SECONDS` (default 300, finite values from 1 to 3600)
sets the execution window per collection attempt, beginning at claim; queue waits
do not count. Both Compose deployments forward it. Scheduling a new automatic
`retry_round` atomically clears `collection_deadline_at`; its next claim starts a
new window. Recovering the same acquisition preserves its deadline. An admitted
manual retry starts a new cycle.

Expiry returns `collection_budget_exhausted` and an incomplete outcome, retaining
validated datasets and committed model votes. It does not cancel persistence or
release a slot while blocking work is still running. Built-in public HTTP and
trusted LLM/browser transports use absolute request deadlines through headers,
chunk framing and body reads. DNS runs in a process-wide pool of four daemon
threads with at most four admitted lookups. Waiting for capacity or resolution
consumes the same request and collection budget; late answers cannot connect.
An OS lookup itself cannot be killed: four stuck lookups temporarily exhaust DNS
capacity until they finish or the process restarts. Injected blocking callbacks
remain cooperative limits. The collection window does not bound final persistence.
Browser leases and proxy tunnels are capped at 300 seconds, navigation at 30
seconds and probes at 10 seconds/64 KiB. See the
[collection reference](reference/collection.md) for extraction and validation rules.

The catalogue can reuse a collected dataset without revalidation. No periodic
refresh is installed, and cache presence does not prove a complete collection.

## Internal operational logs

The API enables the `collector.operations` logger at startup. It writes JSON lines
on stderr, available only through server/container logs; no route or frontend view
exposes them. No external monitoring service is required. Inspect a bounded window:

```sh
docker compose logs --since 15m --tail 500 --timestamps ai-commons-api
```

Events cover `collection_started` / `collection_finished`,
`classification_started` / `classification_finished`, `provider_request`,
`persistence_retry`, `persistence_finished`, `persistence_duration`, and failures
in `worker_poll` or collection/classification execution. Durations use a monotonic
clock. A worker's finish duration includes execution and terminal persistence,
including retry waits; it excludes time spent queued. Provider duration covers the
HTTP request and parsing, not subsequent classification-domain validation. Outcomes
are fixed categories: `started`, `success`, `failed`, `retry`, `timeout`,
`network_error`, `http_error`, `invalid_response`, and `configuration_error`.
A failed persistence duration also records a permanent error or interrupted wait.

Internal `job_id` / `candidate_id` fields correlate events across executor and
voter threads. They are not metric labels. Events never include URLs, prompts,
request bodies, credentials, provider names/models or response/exception text.
Existing application persistence and public error presentation are unchanged.
Logging-handler failures are ignored so they cannot fail model calls, persistence
or collection. These logs are best-effort diagnostics, not an audit trail.

High provider durations point to model-call latency. Repeated persistence retries
point to a database or pool problem; the model result is retained without repeating
the model call. A start event with no finish may mean ongoing work or an interrupted
process: check container status and persisted job status before concluding failure.
Parallel voter durations overlap and must not be summed as wall-clock duration.

To inspect backlog, run this read-only SQL through an administrative PostgreSQL
connection. It returns only queue counts and the oldest queued age in seconds.
`updated_at` is reset when work is enqueued or explicitly retried; once claimed it
is overwritten, so this query does not measure historical per-task queue wait.

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '5s';
SELECT 'collection' AS queue, count(*) AS queued,
       COALESCE(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - min(updated_at))), 0)
           AS oldest_wait_seconds
FROM collection_jobs WHERE status = 'pending'
UNION ALL
SELECT 'classification', count(*),
       COALESCE(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - min(updated_at))), 0)
FROM repository_candidates WHERE classification_status = 'queued';
COMMIT;
```

A growing oldest age with active workers suggests backlog. No claimed work plus
`worker_poll` failures suggests that workers cannot access or finalize queue work.
These are diagnostic indicators, not guarantees of the underlying cause.

## Diagnostic history

Owner-scoped diagnostic exports exclude raw exceptions, HTML, cookies and invalid
model responses. Stored observations are sanitized again on read. Search exports
are bounded snapshots; use paginated job/candidate history for older entries.
See [API diagnostic history](api-integration.md#diagnostic-history) for endpoints,
pagination and truncation limits, and the
[investigation guide](../research/search-diagnostics.md) for interpreting evidence.

## Outbound network policy

The runtime image removes unused global `setuptools`/`wheel` build tools after
installation, including their vendored dependencies. Rebuild and rescan images
before deployment: Python lockfile checks alone do not inspect the base image.
The 2026-10-18 scan found no high/critical Python-package findings, but reported
eight high-severity advisory IDs across Debian 13.7 packages, without a fixed
version listed for this release. These affect util-linux mount helpers
(CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410), ACL
(CVE-2026-54369), ncurses (CVE-2025-69720), systemd-homed (CVE-2026-16742), and
Perl (CVE-2026-9538). The API has no mount, terminal or Perl execution endpoint,
and systemd-homed is absent from the image; no reachable API exploit was
demonstrated. This is deployment triage, not proof that the image is unaffected.
Track vendor updates through the [Debian security tracker](https://security-tracker.debian.org/tracker/),
rebuild when fixes land, and retain `util-linux`: its `setpriv` command implements
the privilege drop below. Do not remove the bootstrap protection to quiet a scan.

The backend image starts with a short bootstrap that installs an nftables
`inet collector_egress` table inside its own network namespace. The API starts
only after that succeeds. Bootstrap needs `NET_ADMIN`, `SETUID`, `SETGID`, and
`SETPCAP`; Compose drops all other capabilities. Before executing the application,
`setpriv` switches to UID/GID 10001 and clears all capability sets, including
the bounding set, with `no_new_privs`. The API and its children cannot remove
the firewall or regain these capabilities.

The output policy permits:

- replies to incoming API connections;
- UDP/TCP 53 to nameservers from the container's `/etc/resolv.conf`;
- TCP 5432 to the addresses of the trusted `postgres` service, resolved at startup;
- TCP 80/443 to public destinations outside the blocked ranges and extra CIDRs;
- IPv6 neighbour discovery with hop limit 255, necessary for local link operation.

All remaining output is dropped, on every attached interface. The filter runs
before Docker's embedded-DNS output DNAT so its resolver continues to work.
IPv4 private, loopback, metadata/link-local, CGNAT, documentation, benchmark and
multicast ranges are blocked. IPv6 is restricted to native global unicast,
excluding special/transition ranges. Direct nonstandard HTTP ports, private
proxies and private LLM endpoints will therefore fail in this deployment.

The API shares the database exception with the collector because they run in
one process. The HTTP client's independent address validation still rejects
all private destinations, including PostgreSQL. Keep both layers enabled.

The rules are replaced atomically on API restarts. Restart the API after
recreating PostgreSQL if its addresses change; the previous rules fail closed
for the new address until refreshed. Do not use host networking, a shared
network namespace, or override the container entrypoint. Runtimes that cannot
provide nftables/these bootstrap capabilities require an equivalent policy
managed by the infrastructure; this image deliberately refuses unfiltered startup.

Python processes launched directly on the development host use the protected
HTTP transport but do not install a host firewall. For remote production,
verify the host/provider firewall and add any internally routed public/admin
CIDRs to `EGRESS_BLOCKED_CIDRS`. A separate collector worker would be required
to remove its process-level database exception entirely.

## Verify the deployed infrastructure

After deploying to the internal EPFL host:

```bash
curl --fail --show-error --silent -o /dev/null "http://${PUBLIC_HOST}:1312/ai-commons/api/docs"
curl --fail --show-error --silent "http://${PUBLIC_HOST}:1312/ai-commons/api/health"
curl --fail --show-error --silent --max-time 3 "http://${PUBLIC_HOST}:1312/ai-commons/api/ready"
docker compose port postgres 5432
docker compose exec ai-commons-api nft list table inet collector_egress
```

Expect successful API documentation, health and readiness responses without an
HTTPS redirect, and no published PostgreSQL port. If curl succeeds but the
browser still redirects, clear its cached redirect/site data and retry the
explicit HTTP URL. The firewall inspection uses `docker exec` as the trusted container
administrator; the application process itself has no capabilities. Verify
its `Uid`, `Gid`, `CapEff`, `CapBnd`, and `NoNewPrivs` in `/proc/1/status`.

### Liveness and readiness

`GET /health` is cheap liveness: HTTP 200 with `{"status":"ok"}` means the
process can serve a request. It never accesses PostgreSQL or model configuration.
`GET /ready` requires completed startup, healthy ownership and worker consumers,
an initialized database pool, nonblank keys and effective model names for the
three default voters, and a successful `SELECT 1` through that pool. Default
model names are accepted when their overrides are absent;
explicitly blank overrides and missing/blank keys fail readiness. These local
configuration checks cannot establish whether a provider accepts a key or serves
a model. Neither endpoint calls LLM providers or incurs model charges.

The database readiness probe has one two-second acquisition/query budget.
Timed-out query connections are closed before cancellation and returned to the
pool for replacement. No new pool is created and no migration or schema scan is
run by a probe. Failures return only HTTP 503 with `{"status":"unavailable"}`;
exception messages and configuration values are not returned or logged by the
endpoint. Readiness responses use `Cache-Control: no-store` and require no login.
Temporary pool/query failures can recover on a subsequent probe while the
ownership session remains healthy. Ownership loss requires an API restart after
repair; it is not silently reacquired. A reopened pool still needs normal schema
initialization.

Uvicorn does not serve HTTP until startup finishes: during migrations or failed
startup a monitor may get a connection failure, not a 503. The application clears
its ready state before workers drain on shutdown. Worker persistence degradation
and consumer failure are included in readiness. This check does not certify
provider reachability or every business operation, and does not repair failures.

Use the external deployment URL above for release checks and monitoring, for
example every 30 seconds with a three-second client timeout. Treat connection
failures, timeouts and non-200 responses as unavailable; investigate repeated
failures. Do not automatically restart the API for database unavailability or a
temporarily exhausted pool. The existing container firewall blocks loopback HTTP,
so an in-container localhost Docker healthcheck is not added. These endpoints do
not themselves configure alerts or change Traefik routing. Shared proxy rate
limits also apply; avoid aggressive polling. Existing database-IP firewall rules
still require an API restart if recreating PostgreSQL changes its address.
Also check from another machine that no legacy port mapping or host/provider
firewall rule exposes PostgreSQL or a direct API port. These are deployment
checks; repository tests cannot certify an external Traefik installation.

## Regression checks

```bash
.venv/bin/pytest tests/test_safe_fetch.py tests/test_container_entrypoint.py
docker build -f backend/Dockerfile -t global-health-security-check:local .
EGRESS_TEST_IMAGE=global-health-security-check:local \
  .venv/bin/pytest tests/test_container_egress.py
```

The Docker test creates disposable IPv4/IPv6 containers and a network, without
host mounts or published ports, and cleans them up. It checks database/DNS
access, blocked internal HTTP and loopback access, public HTTPS, privilege
removal, restart behavior, and refusal to start without firewall privileges.
It needs Docker and outbound HTTPS access to `example.com`; set
`EGRESS_TEST_DOCKER` if the Docker executable is outside `PATH`.

References: [Python TLS](https://docs.python.org/3.11/library/ssl.html),
[Traefik entrypoints](https://doc.traefik.io/traefik/reference/install-configuration/entrypoints/),
[Docker DNS](https://docs.docker.com/engine/network/#dns-services), and
[setpriv](https://man7.org/linux/man-pages/man1/setpriv.1.html).


## Schema validation and retired source administration

The single database schema baseline is version 1.
`backend/app/db/migrations/v001.py` creates the complete schema in an empty
database, including the local/public search access constraint. Repeated startup
preserves owners, command receipts and result records. Earlier pre-release
schemas are unsupported. Startup does not convert, erase or rebuild them.

With `DATABASE_MIGRATE_ON_STARTUP=true` (the default), startup initializes or
validates the schema before serving requests or starting workers. With `false`,
it verifies the exact current version and
persistence contracts without DDL; an outdated or incomplete schema fails
startup, as does a missing or newer unsupported schema. Only `true` or `false`
are accepted.

The initialized state belongs to the current database pool and is cleared
on close/reopen or failed initialization. Business operations use this in-memory
guard without repeating schema-version queries. Scripts that reopen a pool must
call `init_database()` or `validate_database_schema()` before business operations.
Live external schema changes are not monitored per request. New schema changes
use subsequent versioned migrations rather than editing already applied migrations.

To initialize or validate independently of API startup, stop the API first and
keep PostgreSQL running. From an operator checkout with the intended
`DATABASE_URL` configured:

```sh
PYTHONPATH=backend .venv/bin/python -m app.migrate
PYTHONPATH=backend .venv/bin/python -m app.migrate --check
```

Both take the singleton lock and refuse another owner; `--check` performs no DDL
but still requires the API stopped. Then start the API with
`DATABASE_MIGRATE_ON_STARTUP=false`. Startup still recovers interrupted tasks
through normal data writes. For the main Compose deployment, the equivalent
one-off command uses the existing backend image and environment:

```sh
docker compose stop ai-commons-api
docker compose run --rm --no-deps ai-commons-api python -m app.migrate
docker compose run --rm --no-deps ai-commons-api python -m app.migrate --check
# Recreate/start ai-commons-api with DATABASE_MIGRATE_ON_STARTUP=false afterward.
```

For `docker-compose.api.yml`, use its existing `--env-file`/`-f` options and the
service name `api`. The container entrypoint continues installing its network
policy before running either command; no entrypoint override is needed.

The `/sources` administration routes, storage helpers, creation quota and seed
inserts are removed. The schema retains `data_sources` for existing internal
relationships. Source-discovery adapters operate from URLs independently of the
retired administration subsystem.

## Explicit retention maintenance

`PYTHONPATH=backend .venv/bin/python -m app.db.maintenance` reports eligible old
records and deletes nothing by default. No scheduler or startup cleanup is
installed. Defaults are eight days for quota counters, 90 for terminal collection
traces and 90 for terminal model-attempt history. Command receipts, worker
receipts and searches remain unexpired unless their retention flags are supplied.

Configure distinct durations with `--quota-days`, `--trace-days`,
`--vote-history-days`, `--worker-claim-days`, `--command-days` and `--search-days`.
Each accepts positive integer days up to 36500. Command pruning requires an
explicit `--idempotency-window-days` no greater than
command retention; search retention must cover command retention when both are
set. Removing receipts ends unlimited replay protection for those keys, so align
the selected window with clients before applying it.

For example, review this dry-run before selecting the corresponding apply policy:

```sh
PYTHONPATH=backend .venv/bin/python -m app.db.maintenance \
  --command-days 90 --idempotency-window-days 30 --worker-claim-days 90
```

Review the dry-run report, stop the API, then repeat the reviewed command with
`--apply`. Apply holds exclusive ownership and deletes bounded transactional
batches (`--batch-size` defaults to 1000 per category; maximum 10000). Queued or
running tasks and targets of retained receipts are protected. Dataset records,
distributions, current votes and run snapshots remain. Search cleanup excludes
classification runs, referenced jobs and retained receipt targets; it therefore
does not bound every table's lifetime. A timeout or failure rolls back the entire
invocation; failures print a controlled category/message without a connection
traceback. Review the report and run another explicit batch if needed. Dry-runs
can run while the API serves; applying a policy requires the API stopped.

## Traffic limits and shared EPFL addresses

Application labels attach a per-IP token bucket to the existing Traefik API
router before prefix stripping. No change to shared Traefik static configuration
is required.

| Router | Average | Period | Burst |
| --- | ---: | --- | ---: |
| API (`/ai-commons/api`) | 200 | 1s | 400 |

Optional deployment variables are `TRAEFIK_API_RATE_AVERAGE` and
`TRAEFIK_API_RATE_BURST`. Use positive integers; an average of zero disables
Traefik limiting. Recreate the API container after changing labels.

`API_MAX_REQUEST_BODY_BYTES` defaults to 65536 bytes and must be an integer from
1024 to 1048576. The API counts received bytes before JSON parsing, including
chunked requests and missing or incorrect `Content-Length`, returning 413 before
authentication or command admission when exceeded. The main Traefik router also
uses `body-ai-commons-api.buffering.maxrequestbodybytes` with the same setting,
before prefix stripping. The standalone API has its ASGI guard and can use an
external proxy's corresponding body limit. This cap is independent of rate
limits, workload quotas and connection/read timeouts. A disconnected incomplete
body cannot admit a command.

`API_REQUEST_BODY_TIMEOUT_SECONDS` defaults to 30 (valid 1–120). It bounds the
whole upload, including empty chunks and slow streams; expiry returns 408 before
command admission. Configure the upstream proxy's header, TLS and upload limits
as well: the ASGI timer begins only after the request reaches the API.

`DATABASE_STATEMENT_TIMEOUT_MS` defaults to 30000 (1000–300000), and
`DATABASE_LOCK_TIMEOUT_MS` defaults to 5000 (100–30000, no greater than the
statement timeout). Every pool connection receives these limits. Schema setup
temporarily uses 120 seconds per statement and 30 seconds per lock; maintenance
keeps its shorter limits. Request timeouts return 503 without database details.
Workers retry transient lock contention and retain computed outcomes during
storage failure, rather than repeating model calls.

The default source is the direct client IP **seen by Traefik**, not an arbitrary
`X-Forwarded-For` header or session cookie. Users behind EPFL NAT/VPN share a
bucket. If another proxy sits in front of Traefik, verify that topology before
configuring `ipStrategy`; `FORWARDED_ALLOW_IPS` only controls Uvicorn's trust of
Traefik, not Traefik's own source selection. Limits are per Traefik instance and
reset when it restarts; these are traffic guards, not durable workload budgets.

A client polling one progress snapshot every two seconds offers roughly half
a request per second per followed search. Twenty clients following one search
each would therefore offer about 10 regular progress reads/second, plus other
API activity. Multiple tabs and searches increase that traffic.

The opt-in synthetic benchmark below models 14 requests/second per identity:
5 identities offer 70 req/s, 10 offer 140, and 20 offer 280. In that benchmark,
the initial burst can hide overload for roughly five seconds before sustained
traffic receives 429s. This assumption describes the benchmark rather than a
required client polling rate. The 200/400 setting is an initial traffic policy,
not measured application capacity; measure representative use before changing it.

Backend quotas remain independent: 20 new sessions/minute/IP, 10 searches/minute/
session, 30 searches/minute/IP, and 60 admitted classification work items/minute/IP.
Thus six searches returning ten candidates can exhaust the IP work budget even
while Traefik allows all requests. GET polling does not consume backend workload
quotas. Do not increase workload budgets solely because proxy polling is throttled.

For a 429, inspect the existing Traefik access log (when enabled by infrastructure):
`DownstreamStatus=429` with no upstream request/`OriginStatus` indicates a proxy
rejection, whereas `OriginStatus=429` identifies the backend. Backend quota
responses carry JSON `detail` and `Retry-After`; Traefik normally returns plain
text. Clients should handle both, respect `Retry-After`, and avoid automatically
replaying a costly POST. Correlate logs when diagnosing live traffic; body format
alone is not a permanent identification contract.

Run the isolated proxy tests with:

```sh
TRAEFIK_TEST_IMAGE=traefik:v3.7.5 .venv/bin/pytest tests/test_traefik_rate_limits.py -s
```

These tests load the Compose router/middleware labels into an isolated Traefik
with a counting upstream and 5/10/20 identities from one source IP. They verify
the configured defaults, then lengthen only the test refill period to one hour
to exercise burst exhaustion and verify that diagnostics do not consume the API
bucket. They do not mount the Docker socket, read production `.env`, or call model providers. Backend session,
admission and polling quotas are covered by `tests/test_public_quotas.py` against
PostgreSQL. Neither suite certifies the live forwarding chain or throughput.

The original ten-second polling benchmark remains opt-in:

```sh
TRAEFIK_LOAD_BENCHMARK=1 TRAEFIK_TEST_IMAGE=traefik:v3.7.5 .venv/bin/pytest tests/test_traefik_rate_limits.py -k same_ip_polling -s
```

It uses the unmodified production periods and requires a sufficiently fast load
generator. Its duration assertion measures benchmark validity, not application
correctness; it is not a CI gate. No production limit is increased for slower CI.

### Pipeline outcomes

Search completeness and collection outcomes are included in the initial schema.
Missing verification evidence is treated conservatively as incomplete; see
[pipeline outcomes](reference/pipeline-outcomes.md).

## Public API boundary

The backend image and Compose files start `app.main:app`, the core API. They do
not copy or import the private `interface_web/` directory. Search creation,
progress, latest search, datasets by ID and full search diagnostics are available
without a web interface. Manual retry and individual browsing/history routes
belong to the separately maintained private interface and are not shipped here.
Operational notes about persisted retry cycles describe shared worker state;
they do not imply the core exposes a manual HTTP retry route.
