# Deployment on the internal EPFL network

The main `docker-compose.yml` targets an existing Traefik on the external
`traefik` network. The gpu217 deployment uses HTTP on external port 1312,
without TLS or HTTPS redirection. It does not publish database or API ports.
For a Python backend running on your laptop, use `docker-compose.local.yml`
instead; its database port is bound only to `127.0.0.1`.

## Use the existing external Traefik

The existing `web` entrypoint must receive traffic from host port 1312.
[The example static configuration](../deploy/traefik.example.yml) listens on
container port 80, which requires a `1312:80` port mapping on the external
Traefik container. Preserve the existing mapping if HTTP already reaches
Traefik successfully. The application Compose file does not start or reconfigure
that external Traefik.

Do not modify the shared Traefik configuration or attach the application to
`root_mmore-prod`. The application uses labels and the external `traefik`
network specified by the infrastructure administrator. Declaring a network
external does not attach Traefik to it: verify both sides are already connected.
If they are not, ask the administrator to confirm the intended network.
No certificate resolver or port 443 is required for this internal HTTP deployment.

### Anonymous search on internal HTTP

Configure the [temporary HTTP session option](anonymous-visitor-sessions.md#temporary-internal-http-access)
before rebuilding the app. It is disabled by default. The API base path is
`/ai-commons/api`; the configured origin is `http://gpu217.rcp.epfl.ch:1312`,
without a path. Public mode does not require `API_ACCESS_TOKENS`; token mode
still validates them at backend startup.

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

Set the deployment environment (in addition to the secrets in the README):

```bash
export PUBLIC_HOST="gpu217.rcp.epfl.ch"  # hostname only, without scheme/port/path
# Optional: public CIDRs routed to internal/admin services in your infrastructure.
# Comma-separated, strict IPv4/IPv6 CIDRs; DNS and PostgreSQL exceptions take precedence.
export EGRESS_BLOCKED_CIDRS=""
docker compose config --quiet
docker compose up -d --build
```

Open `http://gpu217.rcp.epfl.ch:1312/ai-commons/`.
Both application routers use `web` and the configured `Host` rule. The API
router keeps its higher priority so `/ai-commons/api` reaches port 8001.
There is no TLS, HSTS, or HTTPS redirect middleware in this deployment.

## Collection execution

Run exactly one API process and one API instance against the database. The image
explicitly starts Uvicorn with `--workers 1`. Do not scale replicas or overlap old
and new API instances during a deployment: startup recovery would mark the other
instance's running jobs as interrupted. Stop the old instance before starting
its replacement. Worker leases and multi-instance recovery are not implemented.

`collection_jobs` is the persistent queue; no additional broker or table is
required. After startup recovery, backend consumers poll committed `pending`
jobs. `COLLECTION_MAX_CONCURRENCY` (default `2`) bounds concurrent collection
runs inside this single process; it is not the number of API processes. Each
consumer claims one job atomically only when its execution slot is available.

- Pending jobs survive restart and are picked up automatically.
- Jobs left running by an interrupted process become errors at the next startup;
  they are not automatically retried.
- Normal application shutdown stops taking new work and waits for current
  collections to finish. The container's stop grace period can force termination
  before that finishes; allow enough time if draining is required.
- A repeated classification reads its existing collection, including an empty
  or failed result. `POST /collector/collection-jobs/{job_id}/retry` explicitly
  requeues an owned failed job and consumes the existing classification quota.

Classification decisions and initial collection reservations share one
transaction. If reservation fails, the decision rolls back too; an explicit
classification retry reuses all already persisted valid votes. LLM and network calls stay outside
the transaction. Classification requests now persist as `queued` on existing candidates before
HTTP 202 is returned. `pending` means discovered but not requested; workers never
execute it. `CLASSIFICATION_MAX_CONCURRENCY` (default `2`) bounds the separate
classification pool. Queued requests survive restart; interrupted `classifying`
candidates become errors and require an explicit `retry=true` request. An LLM
response lost before persistence may need another call; no automatic retry is
added. Both pools share the same bounded consumer implementation.

Schema version 6 adds `classification_runs` and `classification_votes`, with
input/configuration fingerprints, per-voter attempts, and progress on candidates
and collection jobs. Migration runs automatically at backend startup without
removing existing data. Existing historical decisions are not backfilled as votes.
Each response is validated and committed before waiting for the remaining voters.
A changed input or ensemble configuration starts a separate run. No transaction
stays open during an external request. Startup marks interrupted votes as failed
without discarding successes. The CLI has no persistent vote store; this recovery
applies to backend workers.
Deploy backend and frontend together: classification submission now returns an
intermediate state, followed through authenticated GET requests. The frontend
restores the most recent search containing repository candidates on load and
provides a restore button. It never submits its unrequested candidates implicitly.
This is recovery of the last repository analysis, not a complete search history.
The single-process/single-instance constraint also applies to classification.

## Outbound network policy

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

After deploying on gpu217:

```bash
curl -I "http://${PUBLIC_HOST}:1312/ai-commons/"
curl --fail --show-error --silent "http://${PUBLIC_HOST}:1312/ai-commons/api/health"
docker compose port postgres 5432
docker compose exec ai-commons-api nft list table inet collector_egress
```

Expect a successful frontend response without an HTTPS redirect, a successful
health response, and no published PostgreSQL port. If curl succeeds but the
browser still redirects, clear its cached redirect/site data and retry the
explicit HTTP URL. The firewall inspection uses `docker exec` as the trusted container
administrator; the application process itself has no capabilities. Verify
its `Uid`, `Gid`, `CapEff`, `CapBnd`, and `NoNewPrivs` in `/proc/1/status`.
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

Startup validates and migrates the schema before serving requests or starting
workers. The initialized state belongs to the current database pool and is cleared
on close/reopen or failed initialization. Business operations use this in-memory
guard without repeating schema-version queries. Scripts that reopen a pool must
call `init_database()` before business operations. Apply schema changes through
startup migration; live external schema changes are not monitored per request.

The `/sources` administration routes, storage helpers, creation quota, and seed
inserts are removed. Historical `data_sources` rows are preserved. No data-dropping
migration is part of this cleanup, and source-discovery adapters still operate
from URLs independently of the retired administration subsystem.
