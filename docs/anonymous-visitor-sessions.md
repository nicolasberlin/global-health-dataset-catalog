# Anonymous visitor sessions — backend foundation

The backend can recognize a browser without asking its visitor to supply an API
token. The backend also limits public workload. The default remains
`API_AUTH_MODE=token`; Compose and the frontend retain their existing behavior.
Public rollout still requires frontend session initialization, HTTPS, trusted
proxy configuration, and general traffic limits at the reverse proxy.

## Configuration

`API_AUTH_MODE=public` requires:

| Variable | Requirement |
| --- | --- |
| `API_SESSION_SECRET` | Random server-side secret, 32–512 characters, no surrounding whitespace. Keep stable across restarts. |
| `API_PUBLIC_ORIGIN` | The browser's HTTPS origin, including any non-default port, without a path or trailing slash. Example: `https://health.example`. |

Startup rejects missing or invalid settings. `API_ACCESS_TOKENS` is not required
in public mode. Never put the session secret in a `VITE_*` variable or a browser
response. Changing it invalidates all existing visitor cookies. The public
origin is configured explicitly rather than inferred from forwarded headers.

Use one HTTPS origin for the frontend and API. The current internal EPFL HTTP
deployment does not meet this prerequisite. TLS may terminate at the trusted
reverse proxy; the API does not need to terminate TLS itself. Local development
can continue using the existing loopback-only `local` mode.

## Browser contract

1. Call `POST /session` from the configured origin. No request body is required.
2. A `204` response sets an anonymous session cookie if the existing one is
   missing, invalid, or expired. Repeated calls with a valid cookie reuse it
   without extending its lifetime or consuming another creation quota unit.
   New sessions are limited per IP. No credential is returned in the body.
3. Send the cookie with subsequent collector requests. Search, progress reads,
   and retries resolve it to the existing `APIPrincipal.owner_id`.
4. A protected request with a missing or expired cookie returns `401` and does
   not create another session or start work. The frontend must handle recovery;
   it must not automatically replay costly POST requests.

The cookie is named `__Host-global-health-session`, with `Secure`, `HttpOnly`,
`SameSite=Lax`, `Path=/`, and no `Domain` attribute. Its seven-day expiration is
checked on the server, even if a client retains the cookie longer. It contains
only a signed random identifier, not provider credentials or user information.
ItsDangerous implements signing and timestamp validation. The signing key stays
on the server; the cookie is still a credential for this visitor's own work.

The browser shares this cookie across its tabs. Another browser or an expired
session receives a different owner. Losing a cookie loses access to its previous
owned searches; this step does not implement accounts or history transfer. It
does not delete existing searches, collected datasets, or running jobs.

## Access policy

The existing ownership filters and per-owner PostgreSQL quotas continue to
apply. Catalog endpoints remain public. Existing collector operations use the
visitor owner in public mode; neither a client-supplied owner ID nor a Bearer
header can select a different identity. Public mode accepts only visitor
cookies, token mode accepts only configured Bearer tokens, and local mode keeps
its existing loopback checks. OpenAPI documents both credential schemes with
their corresponding deployment modes. `/session` returns `404` outside public
mode.

Cookie creation and state-changing session requests require an exact allowed
`Origin` header. Missing, `null`, HTTP, and foreign origins are rejected with
`403`, including requests carrying an otherwise valid cookie. CORS is not used
as authorization. Successful session issuance and protected responses carry
`Cache-Control: no-store`.

No database migration or user table is needed: the signed identity becomes a
namespaced `visitor:<random-id>` owner in the current schema. IP and global
limits remain effective when a visitor discards cookies and creates a new identity.

## Workload limits

All limits are configurable positive integers. These defaults are initial
operational settings, to be adjusted for traffic and provider capacity:

| Setting | Default | Scope |
| --- | --- | --- |
| `API_SEARCH_REQUESTS_PER_MINUTE` | 10 | Search requests per owner, including local results |
| `API_CLASSIFICATION_REQUESTS_PER_MINUTE` | 20 | Admitted candidate pipelines or explicit retries per owner |
| `API_PUBLIC_SESSIONS_PER_IP_PER_MINUTE` | 20 | New visitor cookies per IP |
| `API_PUBLIC_SEARCHES_PER_IP_PER_MINUTE` | 30 | Search requests per IP, across cookies |
| `API_PUBLIC_CLASSIFICATIONS_PER_IP_PER_MINUTE` | 60 | Admitted candidate pipelines or retries per IP |
| `API_PUBLIC_ONLINE_SEARCHES_PER_DAY` | 500 | External metadata searches across all public visitors |
| `API_PUBLIC_WORK_ITEMS_PER_DAY` | 500 | Admitted candidate pipelines or explicit retries across all public visitors |
| `API_PUBLIC_MAX_ACTIVE_WORK_ITEMS` | 100 | Queued/running classifications plus pending/running collections |
| `API_PUBLIC_MAX_CANDIDATES_PER_SEARCH` | 10 | Unique candidates admitted from one public search |

Owner limits also apply in token/local mode. The other settings apply only to
public sessions. Startup validates them before accepting traffic. Existing
classification and collection worker concurrency settings still control how
many jobs execute at once; the active-work limit also bounds the waiting queue.

A work unit covers one candidate's classification and its possible automatic
collection. An explicit classification or collection retry reserves another unit.
This is a workload budget, not an exact LLM-call or monetary budget: a pipeline
may involve several ensemble votes. Provider-side spending limits are still
needed for a strict financial cap. Reused results and polling do not reserve
new work units.

Counters use the existing PostgreSQL `api_rate_limits` table, with fixed minute
or UTC-day windows. Batch reservations, queue admission and database writes
share a transaction: rejection or persistence failure rolls back the whole batch
and its work counters. Concurrent retries of the same job/candidate charge only
the request that actually changes it to queued/pending. A short transaction-level
advisory lock serializes work admission; workers and external network calls do
not hold this lock. Collection follow-up moves an existing pipeline slot from
classification to collection rather than adding another admitted unit.

Search request quotas are charged before local lookup. The external-search
budget is charged immediately before calling providers, including attempts that
fail; these external calls cannot be undone. Local results remain usable after
the external budget is exhausted. Results exceeding the per-search candidate
cap are truncated after deduplication and the response includes a warning.

Quota exhaustion returns `429` with `Retry-After`. A full processing queue returns
`429` with a five-second retry delay. Quota-storage unavailability fails closed;
request-quota failures return `503`. No external work is authorized by a failed
check. Catalog and progress reads do not consume workload quotas; general read
traffic limiting belongs at the reverse proxy in the deployment step.

## Client address and operations

IP limits use `request.client.host` as resolved by the ASGI server, not arbitrary
`X-Forwarded-For` values read in application code. Configure Uvicorn and the
reverse proxy to trust only the actual proxy peers and prevent direct public
API access. Do not use unrestricted forwarded-header trust. Without correct
proxy configuration, visitors may all share the proxy's IP quota.

The quota key is an HMAC of the address using the server secret; raw addresses
are not stored in quota rows. IPv4-mapped addresses normalize to IPv4, and IPv6
addresses share a quota within their `/64` prefix. Rotating the session secret
also resets IP identities, but does not reset the global daily counters.

Deployment maintenance should periodically remove old counters, independently
of search history. For example, `DELETE FROM api_rate_limits WHERE updated_at <
NOW() - INTERVAL '8 days'` removes only expired quota state. This change does not
install an external maintenance scheduler or modify the deployed containers.

## Validation

Run `.venv/bin/pytest tests/test_security.py tests/test_visitor_sessions.py tests/test_public_quotas.py`.
The HTTP tests cover cookie flags, reuse, independent visitors, expiration,
forged credentials, mode isolation, Origin checks, and propagation of the owner
into collector routes. Set `TEST_DATABASE_URL` to an isolated PostgreSQL test
database to include the real ownership test: a second visitor cannot read or
classify the first visitor's candidate. PostgreSQL tests also cover cookie resets,
IP/global budgets, whole-batch rollback, queue capacity across concurrent requests,
and retries that charge only once. External providers are stubbed; tests incur
no LLM charges.

Browser regression tests exercise the real session route and authentication
dependency over HTTPS in Chromium, Firefox and WebKit, without supplying `Origin`
or cookies manually. Same-origin `fetch()` POST must create an HttpOnly cookie
and authenticate subsequent GET/POST requests. A form POST from a foreign origin
must receive an actual backend `403`, not merely a CORS error.
Only quota persistence is simulated in this harness; PostgreSQL tests
above cover quotas and ownership. This is a session-contract test, not yet a
test of the frontend search interface.

After installing the Python dependencies, run from `frontend/`:

```sh
npm ci
npx playwright install --with-deps chromium firefox webkit
npm run test:browser
```

The harness requires OpenSSL and port 9443, generates a temporary self-signed
certificate and binds only to loopback. Playwright accepts that test certificate;
browser origin and cookie security checks remain enabled. CI runs this suite
as a separate validation job.

Frontend integration and deployment configuration are
subsequent commits. The current frontend still requires its existing access
configuration until that integration is completed.
