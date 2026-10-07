# Bounded LLM recovery

The backend retries failed model votes through its existing PostgreSQL queues.
No browser, new endpoint, background scheduler service or frontend integration
is required. Repository classification and dataset-page classification use the
same policy and durable vote store.

## Policy

| Setting | Default | Meaning |
| --- | --- | --- |
| `LLM_MAX_ATTEMPTS` | 3 | Total invocations per failed vote/cycle for timeout, network failure, provider 429 or temporary unavailability |
| `LLM_INVALID_MAX_ATTEMPTS` | 2 | Total invocations for an invalid model response; no greater than the transient limit |
| `LLM_RETRY_WINDOW_SECONDS` | 120 | Window from the first claimed execution within which automatic retries may start |

Attempt limits include the initial call. The transient limit must be 1–10 and the
window 1–3600 seconds. Invalid settings fail startup. Direct backend execution
caps the default invalid-response limit at the configured transient limit; Compose
explicitly supplies both defaults. Set both limits to 1 to disable automatic
retries. An explicit retry begins a new cycle, subject to existing workload quotas;
there is no new lifetime cap on user-authorized retries.

The first automatic pause is 2–2.5 seconds; subsequent pauses are 5–6.25 seconds.
Provider `Retry-After` takes precedence whenever later. If the next due date would
fall outside the window, processing ends as incomplete and requires intervention.
The provider deadline is never shortened. A queued retry that is claimed after
its window expires cannot invoke an unsuccessful model again automatically.
Collection jobs additionally enforce their persisted [collection budget](collection-budget.md);
an automatic retry must be due before both deadlines.
The LLM window is a retry-start budget, not a wall-clock deadline for an in-flight
request; existing per-request timeouts still apply.

Authentication/configuration errors, oversized responses and unrelated pipeline
failures do not receive automatic LLM retries. If any required failed vote cannot
be retried, the ensemble stops. Technical failure is not converted to a negative
health-relevance vote or a conclusive empty result.

## Durable execution

Schema migration 8 → 9 adds retry-cycle counters, start/due timestamps and vote
attempt tokens. It preserves datasets, associations, vote responses and lifetime
attempt counts. It does not infer a historical retry cycle.

The same candidate or collection job is requeued with its original ID. Waiting
work still occupies admitted workload capacity but releases the worker to run
other due work. Automatic retries do not charge a new work-item admission quota;
provider usage can rise up to the configured attempt limits.

Validated votes, including negative votes, are reused only for the same input,
model configuration and prompt fingerprint. Only unsuccessful votes are invoked
again. Parent round limits also bound retries if inputs change between attempts.
Collection retries fetch the source again using existing network guards, so a
changed page can legitimately produce a new fingerprint.

Transient database failures retry only the SQL operation, retaining any returned
model response in memory. Claim and completion tokens make lost acknowledgements
idempotent and reject obsolete or conflicting writes. If a terminal vote save
fails permanently, a new explicitly admitted cycle can reclaim the abandoned vote;
its replacement token prevents the former attempt from writing over it.

Scheduled retries survive restart. Work interrupted while executing is marked
`processing_interrupted` and requires an explicit retry. Committed successful
votes remain reusable. A provider response lost before commit during a process
crash cannot be recovered: exactly-once external invocation is not guaranteed.
The existing **single API process/instance** requirement remains in force.

Schema migration 10 → 11 also records worker acquisitions atomically in
`worker_claims`. A transient connection failure after commit replays the same
internal acquisition token, retrieving the original attempt rather than leaving
it running without a consumer. Terminal or superseded attempts cannot be
reacquired with an old token. No receipt is written for an empty poll.

The default model HTTP transport refuses redirects; configure the provider's
direct endpoint. Redirect responses report `llm_configuration_error` and require
configuration correction. Malformed or excessively nested JSON responses report
`llm_invalid_response` and follow the bounded invalid-response retry policy.

## API recovery

While waiting, progress exposes `execution_status=waiting_retry`, `outcome=null`
and `polling_required=true`. Diagnostics carry `recovery=automatic`, `retry_at`,
`attempt` and `max_attempts`. Running or immediately queued branches take priority
in the aggregated execution status; their sibling retry diagnostics remain visible.
Legacy candidate/job states remain queued/pending for compatibility.

Existing owner-scoped explicit retry commands are reused. Failed candidates,
failed collection jobs and completed jobs with `outcome=incomplete` can resume.
Jobs whose diagnostics all declare unsupported recovery are rejected. Saved
results and associations remain available even if the retry finds no new datasets.
Another owner's command returns 404. Premature retries return 429 and
`Retry-After` without recording a new command receipt or charging work quota.
Replaying the same idempotency key acknowledges the original command rather than
starting a new cycle. A command on already queued/running work does not accelerate
its scheduled retry.

## Verification

`tests/test_llm_recovery.py` covers policy limits, invalid configuration, provider
deadlines, repository and page recovery using real PostgreSQL, reuse of negative
votes, restart, exhaustion, permanent errors, idempotent SQL retries, stale workers,
manual recovery, ownership, migration and preservation of saved results. Providers
are simulated; no external LLM calls are made. Existing asynchronous pipeline tests
also exercise completion after the submitting HTTP client disconnects.

Frontend integration and production rollout are separate from these backend changes.

Local verification on 2026-10-06: full Python suite **948 passed, 9 skipped**
(optional Docker egress/Traefik tests). After adding three final expiry/mixed-error
cases and preserving the schema's existing diagnostic-column check, the focused
recovery/database suite passed **105 tests**. Ruff, whitespace checks and both
Compose configuration validations passed. PostgreSQL 16 ran in an isolated
disposable container; application data and live providers were not used.
