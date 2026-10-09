# Asynchronous website integration — 2026-10-08

The existing React website now uses the standalone pipeline API. No backend
production code, configuration contract, or database migration changed.
Deploy the current backend (schema 11) and rebuild the frontend together; this
integration does not deploy or restart a running environment.

## Behavior

- Submit a command to `POST /collector/searches` with `Idempotency-Key`, then read
  the returned search ID through the existing progress endpoint. A command's
  HTTP success is admission, not completion.
- Poll initially even with no candidates. Follow `polling_required` at roughly
  two-second intervals, without overlapping requests. Retain the existing
  session cancellation, stale-response protection and Retry-After handling.
  Progress reads time out after 15 seconds; three consecutive failures stop
  tracking until explicit resumption. Starting a new search stops older loops
  without cancelling server-side collection. See [polling details](search-progress.md).
- Restore queued, running, local, empty and failed searches through
  `/collector/searches/latest`. Restoration submits no work.
- Fetch local and collected dataset records through the existing by-ID endpoint,
  at most 100 IDs per request. Local result order follows the search snapshot.
  Missing records produce a details error while available records remain visible.
- Display automatic waits and incomplete outcomes separately from confirmed
  empty results. Retain saved datasets when another stage fails or times out.
- Retry discovery only before candidates/local results have been published;
  retry classification/collection through their existing commands. Incomplete
  `done` collection jobs can also be retried. The backend remains authoritative
  about eligibility, quotas and provider retry deadlines.
- Configuration-required/unsupported diagnostics do not offer a misleading retry
  button. A temporary tracking failure does not mean server execution stopped.
- Keep the agreement filters, catalog navigation and English interface.

## Command and session scope

`api/commands.js` holds uncertain command keys in a WeakMap keyed by the live
session object. Replays of the same command use the same key, including after a
rate-limited replay. Successful acknowledgement clears the key; a genuinely new
command gets another. A changed persisted attempt also resolves an uncertain
retry. No automatic POST loop was added.

Keys are held in memory, not persisted across full reloads. Reload restores the
latest search from the server. Losing/expiring the visitor identity still prevents
restoration of the old owner's searches. No new login, token prompt or model key
was introduced. Internal HTTP deployments can generate random keys without the
secure-context-only `crypto.randomUUID` API.

## Verification

Frontend tests cover admission loss/replay, empty discovery polling, automatic
retry, local ordering, partial results, collection retry, search retry deadlines,
session isolation, malformed acknowledgements, dataset batching and stale reads.
Existing concurrency, classification, agreement, catalog and public-session tests
were adapted to the asynchronous response contract.

Browser tests exercise the built site with the real API routes, response models
and visitor authentication. Persistence/providers are isolated fixtures; tests do
not call external repositories or models. The progress/error scenarios also use
controlled HTTP responses to test lifecycle rendering and polling termination.

Local verification on 2026-10-08: **77 frontend tests passed**, **18 browser tests
passed** across Chromium, Firefox and WebKit. Production Vite build, Ruff for the
browser API harness, and `git diff --check` passed. No external model calls or
production database changes were made. Production deployment has not been verified.

Local verification on 2026-10-09 after bounding tracking: **83 frontend tests
passed** and the production Vite build passed.
