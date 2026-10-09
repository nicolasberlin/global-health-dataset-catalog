# Multi-method collection implementation plan — 2026-10-09

Preserve React/Vite, FastAPI, PostgreSQL, the existing persistent queues,
classification checkpoints, guarded atomic finalization and public outcome contract.

## Architecture

An orchestrator resolves one accepted repository record, trying an official
adapter, HTML/structured metadata, then an optional isolated JavaScript renderer.
All strategies return the same metadata/distribution evidence. Classification,
bounded resource validation and final persistence remain common. Do not turn an
individual candidate into a whole-site crawl. A browser session remains alive
until any required resource probes finish; cookies never enter DB/logs.

The initial policy retains at most one validated distribution, trying at most
three distinct resources. Finding a link alone is not success. Record discovery
and validation coverage explicitly; do not claim exhaustive collection.

## Data

Add owner-scoped persisted method attempts and resource checks, correlated with
job, retry cycle and claim version. Stable resource identity includes repository,
record/version and file identifier when available, not signed access URLs.
Keep execution_status and outcomes results/empty/incomplete. An unresolved access
barrier is incomplete; a recovered strategy failure is history, not a fatal result.

## Delivery

1. Common contracts, barrier diagnostics and additive schema migration.
2. Candidate-path orchestrator, Dataverse dataset/file resolver, deduplication.
3. Optional isolated Chromium worker; bounded same-session resource probes and
   common validation. Shared 180-second deadline, 30-second browser operation cap,
   one browser slot initially. No access to app/model secrets or database.
4. Protected diagnostics/trace endpoint, readable frontend history and coverage,
   explicit idempotent retries, correct terminal wording.
5. Fixtures, DB/API/browser security/recovery tests, actual Harvard file probe,
   deployment instructions and additive rollout. No automatic production rollout.

## Security and reliability

Enforce public destinations for all browser traffic using a network boundary,
including subrequests/redirects/WebSocket/DNS rebinding. Block private ranges and
metadata endpoints; preserve TLS checks. Request/byte/time/memory limits must be
explicit. Never rely on Playwright routing alone. Ordinary JavaScript execution
is allowed; no stealth identities, copied user sessions or CAPTCHA solving.
Keep single API instance, existing guarded claims, preserved votes and datasets.
Interrupted work still follows existing explicit retry policy. Persist history
without overwriting old conclusions; expunge secret headers/URLs/HTML.

## Acceptance

Test API failure recovered by HTML, challenge recovered by rendered page,
session-bound file probe, false challenge positives, stable deduplication,
coverage limits, timeout with partial results, SSRF via subrequest, retries and
stale writes, ownership of traces. Harvard is successful only after the actual
Excel resource passes common bounded validation and its dataset is saved; page
visibility alone is insufficient.
