# Review corrections — 2026-10-07

Implemented locally on `main`, alongside the existing uncommitted collection
budget. No production database was migrated and no external model was invoked
during verification.

## Corrections

1. **Lost worker-acquisition acknowledgements.** `app.workers` generates one UUID
   before retrying SQL acquisition. Search, repository classification and
   collection commit their state transition and `worker_claims` receipt in one
   transaction. A replay returns the original active attempt; a receipt for a
   finished or superseded attempt returns no work. Same-token acquisitions are
   serialized with a transaction advisory lock. Fresh acquisitions retain
   `FOR UPDATE SKIP LOCKED`. Empty polls create neither receipts nor routine
   persistence log events; SQL retry events remain visible.
2. **LLM redirects.** The default HTTP opener refuses redirects, including those
   that could forward authorization to another host. The configured provider must
   be a direct endpoint. Redirects produce `llm_configuration_error`; response
   bodies are closed, including when the collection budget expires. Injected
   transports retain responsibility for their own redirect behavior.
3. **Error-body timeouts.** Distribution probes convert transport failures while
   reading an HTTP error body into an unconfirmed result. Alternative
   distributions can still be checked. Budget exhaustion continues to terminate
   collection with its dedicated diagnostic. Bodyless HTTP errors also remain
   usable on Python 3.9.
4. **Browser response headers.** The API exposes `Retry-After` and `Location` to
   explicitly allowed origins. Existing origin and credential rules remain in
   force.
5. **Sitemap decompression.** Both downloaded and decompressed gzip content obey
   the byte limit. Reading is bounded and checks the collection budget, including
   for concatenated gzip members. Oversized/truncated content is a controlled
   discovery failure.
6. **Deeply nested model JSON.** `RecursionError` while parsing the provider
   envelope or model output becomes `llm_invalid_response`, using the existing
   bounded invalid-response recovery policy.
7. **Duplicated ensemble summaries.** Page and repository classifiers share the
   summary constructor while retaining their own vote serializers and decisions.
   Response fields and stored vote formats are unchanged.

## Migration and operating limits

Schema 10 → 11 adds only `worker_claims`. Existing datasets and tasks are retained;
the supported versioned migrations run during normal backend initialization.
The preceding collection-budget migration 9 → 10 also remains included.
There is no new API endpoint or frontend contract requirement.

Receipts retain one row per acquired attempt, with no expiration policy yet.
Retries of one token must remain sequential within a consumer; receipts do not
provide a distributed worker lease or exactly-once external execution. The
application still requires one API process/instance. A prolonged SQL outage can
delay shutdown; forced termination uses the existing interrupted-work recovery.

## Regression coverage

- `tests/test_worker_claims.py`: real PostgreSQL commit followed by lost
  acknowledgement in all three queues, one consumer execution, concurrent tokens,
  atomic rollback, stale manual/automatic attempts, due dates, cross-queue token
  conflicts, empty polling and data-preserving migration.
- `tests/test_review_network_regressions.py`: redirect handlers and credentials,
  body closing, error-body failures, alternative links, deep JSON and bounded
  gzip decoding. HTTP transports are simulated.
- `tests/test_review_contract_regressions.py`: production CORS configuration
  applied to 429/202 responses and rejection of an unconfigured browser origin.
- Existing ensemble, budget, persistence, ownership and pipeline tests cover the
  combined changes. PostgreSQL 16 runs in a temporary isolated test container.

Verification on 2026-10-07: full Python suite **1,069 passed, 9 skipped** in
63.34 seconds. The skipped cases require optional Docker egress/Traefik images
or benchmark configuration. Ruff and `git diff --check` passed. No frontend
source changed. The temporary PostgreSQL container was removed after testing.
