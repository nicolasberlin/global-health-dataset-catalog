# Total collection execution budget

Each collection job receives a durable deadline at its first execution. Initial
queue time is excluded; subsequent queue time, network work, discovery, extraction,
dataset classification, distribution probes and automatic retry waits consume the
same window. Initial search discovery and repository relevance classification
precede the collection job and are not covered by this particular budget.

`COLLECTION_MAX_DURATION_SECONDS` defaults to 180 seconds and accepts finite values
from 1 to 3600, including fractions. Invalid values fail backend startup. The
180-second default is an initial operational choice, not a measured service-level
guarantee; tune it using representative collection and provider duration events.
Direct Python callers can set `CollectorConfig.collection_max_duration_seconds`.
The environment variable applies to backend job admission/claims.

## Lifecycle and compatibility

Schema migration 9 → 10 adds `collection_jobs.collection_deadline_at` without
rewriting historical outcomes. Historical pending jobs receive their deadline when
claimed. Both the regular worker claim and the legacy explicit start path assign
it atomically. One API instance/process remains required by the existing queues.

Automatic retries preserve the original deadline even across restarts or a
configuration change. A retry is never scheduled at/after the collection deadline
or the LLM retry window, and provider Retry-After is not shortened. A queued retry
that has expired concludes incompletely when a worker claims it, without new
provider or source calls. Manual retries use existing ownership, quotas, command
idempotency and stale-write guards; only a genuinely new admitted cycle resets the
deadline. Replaying a command or acknowledging active work does not extend it.

The persisted UTC deadline is converted once to a monotonic deadline in the
worker. The existing copied context shares it with all three voter threads and
nested collector calls, without changing model inputs or vote fingerprints.
Keep host and PostgreSQL clocks synchronized; the deadline is a persisted wall
clock value, while elapsed checks within each execution are monotonic.

## Actual guarantee

Before new source operations and LLM requests, the collector checks remaining
time. Public HTTP checks include initial requests, redirects, DNS boundaries,
each numeric IP connection and TLS; socket timeouts use the smaller of the
existing per-request timeout and remaining budget. Body reads keep existing byte
caps and check between chunks. Redirect bodies are closed without being drained.
Neither private-network protections nor TLS hostname verification is relaxed.

This is a **cooperative deadline**, not a forced kill. An OS DNS lookup, HTTP
status/header read, existing blocking transport call or injected custom callback
can return late. Socket timeouts are inactivity limits and cannot establish a
strict whole-request time bound. The worker retains its slot until the operation
and all voter threads actually return. It never reports a thread as cancelled
while letting it continue untracked. Custom injected transports remain responsible
for their internal blocking behavior.

Persistence-only retries and final saves intentionally continue beyond expiry.
A complete validated model response remains eligible for checkpointing even if
the budget has run out. An incomplete response is not saved as a successful vote.
Once a blocking call returns, no subsequent external operation is started late.

## Outcomes and retained results

Expiration produces a controlled `collection_budget_exhausted` diagnostic and an
`incomplete` outcome. It is not a negative relevance decision or conclusive empty
search. The normal API's existing errors/outcomes carry this information; the
deadline field stays internal. Frontend integration is unchanged.

Datasets already fully validated in the current run are included in the final
atomic save. If a page already has a proven distribution when a later probe
expires, that dataset and its proven links are retained. Interrupted/unverified
resources never enter the catalogue. Completed failure observations and actual
analyzed-page counts remain in the report. Committed results from prior attempts
and reusable model votes also remain available.

This targeted partial-result handling covers budget expiration. It does not
introduce general per-page recovery for every unrelated fatal exception in legacy
multi-page source collection; that remains a separate deferred decision.

## Verification

- `tests/test_collection_budget.py`: invalid configuration, context reuse and
  cleanup, discovery/HTML/classifier boundaries, retained datasets/links/evidence,
  shared voter deadline, and worker-to-API incomplete outcomes with real PostgreSQL.
- `tests/test_collection_budget_network.py`: DNS/connect/TLS/redirect boundaries,
  shrinking HEAD/GET and model timeouts, bounded streaming, HTTP error cleanup and
  preservation of complete responses at the deadline.
- `tests/test_collection_budget_persistence.py`: schema upgrade, first claim,
  restart, immutable automatic deadline, provider due times, manual ownership,
  concurrent command replay and stale workers.

Tests use simulated providers and a disposable PostgreSQL database; no live LLM
quota is required. No changes to classifier evaluation, periodic link validation,
backup/restore automation or the frontend belong to this implementation.

Verification on 2026-10-07: the complete Python suite passed **1001 tests** with
**9 optional Docker egress/Traefik tests skipped**. Ruff, whitespace checks and
both Compose configuration validations passed. The test run used an isolated
PostgreSQL 16 container and simulated external providers. Production data was
not migrated; migration 10 will run through normal application startup on rollout.
