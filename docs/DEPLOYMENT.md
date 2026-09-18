# Secure deployment

The main `docker-compose.yml` targets an existing Traefik on the external
`traefik` network. It requires HTTPS and does not publish database or API ports.
For a Python backend running on your laptop, use `docker-compose.local.yml`
instead; its database port is bound only to `127.0.0.1`.

## Configure the external Traefik

Merge [the example static configuration](../deploy/traefik.example.yml) into
the actual Traefik configuration. Adapt its operations email and persistent
ACME storage, and ensure ports 80/443 are routed to Traefik. Protect the ACME
file with mode 600. The application Compose file does not start or reconfigure
the external Traefik.

Set the deployment environment (in addition to the secrets in the README):

```bash
export PUBLIC_HOST="catalog.example.org"  # hostname only, without scheme/path
export TRAEFIK_CERT_RESOLVER="letsencrypt"  # must exist in the external Traefik
# Optional: public CIDRs routed to internal/admin services in your infrastructure.
# Comma-separated, strict IPv4/IPv6 CIDRs; DNS and PostgreSQL exceptions take precedence.
export EGRESS_BLOCKED_CIDRS=""
docker compose config --quiet
docker compose up -d --build
```

The domain's DNS must point to the deployment. The example resolver obtains a
certificate with ACME HTTP-01. If your Traefik uses another resolver, set its
name in `TRAEFIK_CERT_RESOLVER`. Having `tls=true` alone does not provision a
trusted certificate.

Both application routers use `websecure`, TLS and the configured `Host` rule.
A separate `web` router redirects `/ai-commons` and its API paths to HTTPS.
The example static configuration additionally redirects all HTTP traffic.
HTTPS responses include one year of HSTS, without extending it to subdomains.
Clients must use an HTTPS URL before sending a Bearer token: a redirect cannot
protect credentials already transmitted in an initial HTTP request.

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
  or failed result. No collection retry endpoint is introduced by this change.

Classification decisions and initial collection reservations share one
transaction. If reservation fails, the decision rolls back too; an explicit
classification retry may repeat the LLM call. LLM and network calls stay outside
the transaction. Classification execution itself is not yet durable across HTTP
cancellation or process interruption. Frontend recovery after a full page reload
also still needs an authenticated listing endpoint.

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

After configuring the real hostname and certificate:

```bash
curl -I "http://${PUBLIC_HOST}/ai-commons/"
curl --fail --show-error --silent "https://${PUBLIC_HOST}/ai-commons/api/health"
curl -I "https://${PUBLIC_HOST}/ai-commons/"
docker compose port postgres 5432
docker compose exec ai-commons-api nft list table inet collector_egress
```

Expect an HTTPS redirect, a successful health response with certificate
verification enabled, HSTS on HTTPS responses, and no published PostgreSQL
port. The firewall inspection uses `docker exec` as the trusted container
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
