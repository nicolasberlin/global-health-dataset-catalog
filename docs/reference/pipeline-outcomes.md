# Pipeline execution, outcomes, and diagnostics

The API contract separates execution from the conclusion supported by the
available evidence. The search-level view
is computed from the existing owner-scoped REPEATABLE READ snapshot; no second
persisted global state is maintained.

## Public contract

`GET /collector/searches/{search_id}/progress` includes `search_id`, `items`,
`polling_required`, and:

- `execution_status`: `queued`, `running`, `waiting_retry`, `finished`, or `failed`.
- `outcome`: `null`, `results`, `empty`, or `incomplete`.
- `active_stages`: executing stages, currently `search`, `classification`, and
  `collection`. Queued work alone is not an active stage.
- `errors`: controlled structured diagnostics, also including search warnings.
- `local_result_count`: the persisted count returned by a local search, or `null`
  when that information was not recorded. The schema also provides persisted
  `local_dataset_ids` and aggregated `dataset_ids`; see [API integration](../api-integration.md).

Collection jobs and `automatic_collection` expose `execution_status`, `outcome`,
and `errors`. Candidates expose classification `errors`. Embedded failed ensemble
votes also carry `errors`. Raw exception strings remain internal.

The compatibility fields `status`, `state`, `error`, and `error_code` remain
available. In particular, `automatic_collection.state = empty` means a completed
job saved zero datasets. Clients must use `outcome` to decide whether that absence
is conclusive.

## Aggregation rules

| Evidence | Execution | Outcome |
| --- | --- | --- |
| Initial search or any downstream task executing | `running` | `null` |
| No executing work, but queued discovery or downstream tasks | `queued` | `null` |
| No running or immediately queued work, automatic retry scheduled | `waiting_retry` | `null` |
| All required checks concluded, datasets available | `finished` | `results` |
| All required checks concluded, no dataset retained | `finished` | `empty` |
| Processing concluded with an inconclusive necessary check | `finished` | `incomplete` |
| Initial discovery failed, or every attempted downstream branch failed | `failed` | `incomplete` |

Active, queued, or scheduled retry work takes precedence over a failure in another branch. A
successful rejection is a concluded branch, not an operational failure. Thus a
mixture of rejected and failed candidates finishes with `incomplete`, whereas
all failed candidates produce `failed/incomplete`. Unrequested legacy `pending`
candidates produce `finished/incomplete` and do not keep polling alive.

`results` and `empty` are limited to the configured exploration scope. Candidate
admission caps produce a persisted `search_scope_limited` warning, without making
checks within that scope incomplete. Provider failures and invalid provider
records can prevent discovery from concluding and mark it incomplete. Historical
searches lack completeness evidence and are conservatively incomplete after
remaining active work concludes. Local searches with missing historical result
counts are never inferred empty from an empty candidate list.

An incomplete result may contain usable saved datasets. A failed alternative
resource does not invalidate a dataset whose required access check succeeded on
another distribution. If no distribution was validated, `restricted` and
`unconfirmed` checks are inconclusive; a confirmed missing resource (`unavailable`)
is a concluded negative check. Inconclusive pages are not counted as semantic
rejections. CAPTCHA/login barriers on landing pages without usable links, and
unexpected non-HTML landing responses, fail collection with a structured cause.
These checks use existing bounded evidence and do not guarantee detection of
every possible access barrier.

The normal collector supplies `verification_complete` in its report. Manually
constructed or historical reports without this evidence remain incomplete.
Known fatal fetch/classifier failures still interrupt a collection job; transient
results from an interrupted job are not persisted unless finalization succeeds. Results
already committed by other jobs remain available.

## Diagnostic shape and recovery

```json
{
  "code": "llm_rate_limited",
  "stage": "classification",
  "message": "The model provider rate limit was reached.",
  "recovery": "manual",
  "retry_at": "2026-10-04T12:10:00+00:00",
  "attempt": 1,
  "max_attempts": null,
  "voter_id": "model-a"
}
```

Messages are rebuilt from stable codes rather than stored exception text. The
stages are `search`, `classification`, `collection`, and `validation`. There may
be several diagnostics per failed ensemble, retaining each failed voter and its
persisted attempt count. A valid negative vote remains successful and reusable.

| Codes | Recovery indication |
| --- | --- |
| `llm_timeout`, `llm_network_error`, `llm_rate_limited`, `llm_unavailable` | `automatic` when scheduled; otherwise `manual` |
| `llm_invalid_response`, `classification_incomplete` | `automatic` when a bounded retry is scheduled; otherwise `manual` |
| `llm_configuration_error` | `configuration_required` |
| `llm_response_too_large` | `none` |
| `repository_unavailable`, `verification_unconfirmed` | `manual` |
| `access_restricted` | `none` (no supported authenticated collection flow) |
| `processing_interrupted`, `persistence_failed`, `processing_failed` | `manual` |
| `legacy_unknown` | Diagnosis unavailable; no inferred historical cause |

`recovery` describes the kind of intervention, not authorization. The existing
owned retry commands and admission quotas remain in force. Failed candidates and
failed, incomplete or eligible empty jobs can be retried explicitly. Jobs whose
diagnostics all declare unsupported recovery are rejected. Bounded automatic
LLM retries emit `waiting_retry` while waiting; polling
continues. `max_attempts` reports the configured limit on retryable LLM failures,
and `attempt` counts that model's invocations in the current retry cycle.

A valid provider `Retry-After` is retained as `retry_at`. It is enforced for both
automatic and explicit retries, including dates beyond the automatic retry window.
An early explicit retry returns HTTP 429 with `Retry-After` and consumes no new
work quota. An acknowledgement of already pending/running work does not advance
its deadline. API admission limits remain separate from provider failures.

Transient vote-storage failures retry only persistence, retaining the response
in memory. Idempotent writes and attempt tokens handle lost acknowledgements and
stale workers. No provider is recalled by a persistence retry. See
[LLM recovery](collection.md#model-retries-and-checkpoints) for configuration, restart semantics and limitations.

## Persistence and verification

The initial schema includes JSON diagnostic arrays for searches, candidates, jobs
and votes, search result-count/completeness fields, collection outcomes, retry
cycles, due times and attempt tokens. Only job outcomes and discovery evidence
are stored; global outcomes are derived. Missing evidence never invents a timeout,
provider status or successful complete verification.

Deployment requires a single backend instance/process. Queued work survives startup;
interrupted work receives `processing_interrupted`. Requeueing clears the current
terminal diagnostic, and older attempts cannot overwrite a new attempt's state.

`tests/test_pipeline_outcomes.py` exercises execution combinations, typed HTTP
errors, sanitization, provider deadlines, and access checks with simulated
providers. `tests/test_pipeline_outcomes_persistence.py` exercises initialization,
local results, report publication, failed-vote causes, partial usable results and
restart/stale-write behavior with a real isolated PostgreSQL database.

`tests/test_llm_recovery.py` verifies the
policy, real database transitions, lost acknowledgements and owned HTTP retries.
