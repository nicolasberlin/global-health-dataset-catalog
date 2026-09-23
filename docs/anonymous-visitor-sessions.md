# Anonymous visitor sessions — backend foundation

The backend can recognize a browser without asking its visitor to supply an API
token. This is the first step towards public access. The default remains
`API_AUTH_MODE=token`; Compose and the frontend retain their existing behavior.
Do not expose the new mode publicly until IP limits, global workload limits,
frontend session initialization, and HTTPS deployment are in place.

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
   without extending its lifetime. No credential is returned in the body.
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
namespaced `visitor:<random-id>` owner in the current schema. A visitor can
discard cookies and create new identities, so the existing per-owner quota is
not sufficient protection for public deployment on its own.

## Validation

Run `.venv/bin/pytest tests/test_security.py tests/test_visitor_sessions.py`.
The HTTP tests cover cookie flags, reuse, independent visitors, expiration,
forged credentials, mode isolation, Origin checks, and propagation of the owner
into collector routes. Set `TEST_DATABASE_URL` to an isolated PostgreSQL test
database to include the real ownership test: a second visitor cannot read or
classify the first visitor's candidate.

Frontend integration, public workload quotas, and deployment configuration are
subsequent commits. The current frontend still requires its existing access
configuration until that integration is completed.
