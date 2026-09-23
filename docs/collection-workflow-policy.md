# Classification, collection, and retry policy

Created: 2026-09-13. Updated: 2026-09-22.

This document describes the implemented workflow and the broader target for
future changes. Sections explicitly marked **proposed** are design decisions,
not guarantees currently provided by the application. They do not change the
scientific acceptance criteria, establish a new licensing policy, or promise
exactly-once execution of external calls.

## Implemented behavior

- Online search persists candidates and queues their initial classifications in
  the same transaction. The browser follows that work; closing it does not stop
  the backend. Legacy `pending` candidates still require an explicit request.
- Classification and collection use bounded consumers of PostgreSQL queues.
  Queued candidates and pending collection jobs survive restart. Interrupted
  classifications, running jobs, and running votes become errors at startup;
  they require an explicit retry. Deployment still requires one API process and
  one instance, without overlapping deployments.
- The accepted decision, initial job reservation or reuse, and candidate–job
  association commit together. A reservation failure rolls back the decision
  too. An already collected dataset can satisfy the request without a new job.
- Reading a candidate, or submitting an already accepted/rejected classification,
  returns its existing decision and follow-up. It never schedules collection.
- Each valid model response is saved separately, including negative votes.
  Explicit retries reuse these responses when the bounded input and entire model
  configuration match. Changed inputs, models, or prompts start a separate run.
  Both classification flows still require three valid responses and two positive
  votes for acceptance. A finalization failure can reuse all three saved votes.
- `POST /collector/collection-jobs/{job_id}/retry` requeues an owned failed job.
  Repeating it while the job is pending/running returns the existing job. It does
  not retry completed empty jobs. It uses the existing classification request
  quota and preserves associations and saved votes. This is not the proposed
  command-ID or new-job-per-attempt protocol described below.
- The frontend restores the latest repository analysis, displays saved vote
  counts and collection progress, and offers explicit retries. Agreement filters
  use each result's vote counts, so historical results retain their own totals.
- Distribution validation records `available`, `restricted`, `unavailable`, or
  `unconfirmed`, with a reason. Failed validations are retained in the collection
  report and job audit. A complete distinction between reliable empty outcomes
  and incomplete verification is still proposed.
- Source administration routes, storage helpers, and startup seeding have been
  removed. Historical `data_sources` rows remain intact. Schema migrations and
  validation run at startup; ordinary operations check initialization in memory
  for the current pool. Closing/reopening the pool invalidates that state.

Separate collection requests, deferred admission, collection-creation quotas,
cooldowns, command IDs, renewable worker leases, and a full paginated work history
remain future work. They are not prerequisites for the implemented fixes.

## 1. Identity, access, and sharing

The catalog is shared. Searches, their candidates, and classification decisions
belong to their user. User identity comes from an authenticated backend entry
point; accepting an `owner_id` argument alone is not proof of authentication.

A user can read a job only if the server has associated it with one of their
candidates. Knowing its ID or having the same URL does not grant access. An
authorized operation on an accepted candidate can create this association when
reserving a job or reusing equivalent active work. The association grants the
public job view, never another participant's searches, candidates, identity, or
the entire history of jobs for that URL. Missing and inaccessible objects both
return `404`.

User operations use owner-filtered SQL. The internal worker interface is separate.
Import rules may help prevent accidental bypasses, but service modules are not
an isolation boundary. Historical associations are preserved only when proven;
migrations do not infer access from matching URLs.

### What can be shared

Classification depends on the candidate and search context. It is not shared
solely by URL. Current automatic collection deduplicates active repository jobs
by URL and records each authorized candidate association.

**Proposed:** a public collection key includes the normalized URL, collection mode
(candidate page or source discovery), and a processing version covering rules,
configuration, and models that can affect the result. Only equivalent inputs can
share work. Functional URL parameters are preserved; mirrors and dataset versions
are not automatically treated as identical. Future user-specific credentials or
inputs require a new sharing boundary.

A SQL constraint enforces at most one active repository collection per URL today.
The proposed versioned key would extend that constraint. Neither prevents every
possible repeated external call after a crash.

## 2. Three distinct concepts — proposed deferred admission

The current implementation uses candidates, jobs, and associations. The job
itself is the durable work item; there is no separate collection-request table.
If reservation fails, acceptance rolls back instead of remaining pending admission.

The broader target distinguishes:

| Concept | Meaning |
| --- | --- |
| Classification | Relevance decision on a candidate's persisted metadata. |
| Collection request | Persisted intent to process an accepted candidate, even when quota prevents immediate job creation. |
| Job | Collection attempt, potentially shared by several requests. |

Under this proposal, initial acceptance and the collection request are atomic,
with one initial request per candidate and classification version. A request can
await admission, be deferred with a reason, reference a job, or be satisfied by an
existing result. These are not independent copies of job status.

An accepted candidate stays accepted when collection is deferred, empty, or
failed. The UI displays the decision separately from the collection outcome.

## 3. Commands and transitions

### Classification — implemented

| State and action | Behavior |
| --- | --- |
| Online search completes | Persist candidates and queue initial classifications atomically. |
| Legacy `pending` + classify | Queue one classification using persisted server inputs. |
| `queued` or `classifying` + classify again | Return the current state without another model execution. |
| `accepted` or `rejected` + classify again | Return the decision and existing follow-up; do not create or retry collection. |
| `error` + classify without explicit retry | Return a conflict requiring an explicit retry. |
| `error` + authorized explicit retry | Queue another attempt under applicable request limits; reuse compatible saved votes. |
| Classification accepts | Persist the decision and initial collection reservation/reuse together. |
| Classification rejects | Persist rejection; no automatic collection. |

Accepted/rejected decisions are not recalculated on reads. Future reevaluation
after a model or rule change is a separate versioned operation, not a way to reroll
votes until acceptance. Reusing a saved negative vote is mandatory on compatible
retries.

### Admission of a collection request — proposed

Admission verifies access, candidate acceptance, and authoritative server inputs.
It then resolves the request in this order:

1. Find an already processed command, if its identifier is known.
2. For ordinary acquisition, reuse an available dataset.
3. Join equivalent active work and record the association.
4. Apply a recent reliable empty result or source-related cooldown.
5. Check waiting capacity and the quota for new collections.
6. Create the job, association, and quota charge in one transaction.

Insufficient quota does not create a fictitious failed job. The request remains
deferred with a reason and, where known, an admission time. An explicit action can
retry admission; reading the state cannot. Admission failure leaves recoverable
intent. Recovering unadmitted intent differs from retrying a completed job.

### Reads, retries, and refresh

Reads never trigger work. The implemented retry endpoint reuses an owned job in
`error`, retains its associations, and rejects another active collection for the
same page. Retrying a shared job is visible to its associated candidates. The
per-voter attempt counter and token preserve vote execution state; a separate
immutable history of collection attempts is not provided.

**Proposed extension:** retrying a failed or reliably empty result creates a new
attempt, or joins the one already created for equivalent work, under section 5.
Old terminal jobs and associations remain. A new job must not silently replace
the displayed job for every historical candidate at the same URL.

Reusing a saved dataset does not mean it was just revalidated; keep its last-check
date. Refreshing an existing dataset is a separate future operation. A failed
refresh must not delete its last stored result; refresh frequency remains to be
defined.

Changing searches, closing the page, or logging out does not cancel backend work
already accepted. Participants cannot cancel each other's shared work. Cancellation
is not part of these changes.

### Repeated commands — proposed

A retry command carries a stable ID bound to the owner, operation, and target.
The server persists its association with the request or job. Repeating the command
finds that attempt even after it finishes; using the ID for another target fails.
The current retry endpoint only deduplicates pending/running work, not commands
across terminal states.

Admission refusal is not a collection attempt. A later explicit action can seek
admission again. A timer expiring or page reload is never that action.

## 4. An empty outcome is not a failure

Execution states stay `pending`, `running`, `done`, and `error`. The target stores
outcome, completeness, and causes separately:

| Observed situation | Target public outcome |
| --- | --- |
| At least one eligible dataset saved | Saved dataset; also report any incomplete checks. |
| No dataset retained and every necessary check in scope completed | Reliable empty outcome, with reason and observed scope. |
| No dataset retained but a failure prevented a required check | Incomplete verification, without claiming that no dataset exists. |
| Execution or persistence failed | Processing error with a structured cause. |

`saved_count == 0` alone does not establish a reliable empty result. Exploration
limits should remain visible: trying some distributions cannot prove that every
resource on the page is unusable. Current defaults try up to three distinct
ranked distributions and save the first valid one.

Validation now retains status and reason, including ambiguous results. Public
views replace technical diagnostics with controlled messages. More detailed
retry-cause mapping remains proposed: temporary error, remote rate limiting,
access refusal, missing resource, incompatible content, prohibited destination,
or internal failure. Unknown exceptions must not become semantic rejections.
An HTTP `403` alone does not prove a licensing or registration requirement.

Historical empty `done` jobs without sufficient diagnostics have an unknown
outcome. Migrations do not invent a reliable 24-hour empty-result lifetime.

Saving the result's datasets and marking the job `done` remains atomic. This
contract does not add partial dataset-result recovery when one page makes a
multi-page collection fail. Persisted model votes are reusable, but recovering
already processed page results is a separate change requiring its own tests.

## 5. Retries and cooldowns — proposed

The following are configurable initial choices, not provider guarantees or
security standards. They are not currently enforced by the explicit retry API.

| Cause | Initial rule | Scope |
| --- | --- | --- |
| Reliable empty result | Reusable for 24 hours; explicit retry afterward. | Collection key and processing version. |
| Temporary resource failure | Explicit retry at least 5 minutes after the attempt ends. | Equivalent work, not just one candidate. |
| Remote rate limit with known delay | Respect the provider delay and any longer local cooldown. | Resource, domain, or provider account as applicable. |
| Misconfiguration, refused access, or prohibited destination | No automatic repetition; configuration/access changes can enable recovery. | Affected dependency or resource. |
| User quota exceeded | Explicit admission after quota becomes available. | That user only. |
| Unknown error | No reusable empty result; internal diagnostic and no blind automatic loop. | Affected operation. |

Reading or reusing an empty result does not renew its validity. A new candidate
cannot bypass it. After expiry, a new initial request can start work; an existing
accepted candidate must use explicit retry.

A shared model-provider outage is a dependency failure, not evidence that every
URL is permanently invalid. Alice exhausting her quota must not stop Bob, who has
his own quota, from requesting the same source.

If internal HTTP read retries are added, allow at most two additional attempts per
eligible call, with backoff, jitter, and a bounded total duration. Every attempt
respects provider restrictions and network policy. This must not introduce an
implicit retry loop for the entire pipeline or model calls. Review client and
worker budgets together to avoid multiplying attempts across layers.

## 6. Quotas and capacity

Current defaults remain 10 searches/minute and 20 classification requests/minute
per owner, with two collection consumers and two classification consumers per
process. Search charges classification quota for unique online candidates before
persisting them. Explicit classification and failed-collection retries use the
classification quota. It measures application requests that may start work, not
individual model calls or every status read. Quota persistence uses its own
transaction.

The broader admission design proposes:

| Measure | Unit and rule |
| --- | --- |
| Request limit | Incoming protected operation. Concurrent requests can count separately even if they produce one execution. |
| New-collection quota | Newly admitted job; creation and charge share one transaction. |
| Cost measurement | Actual model/HTTP calls and processing time, separately from application quotas. |

The user whose request creates a job pays the proposed collection charge. Joining
work, reusing a result, or repeating a processed command does not create another
collection charge, but applicable request limits still apply. Failed attempts
remain counted. An explicit new attempt consumes a new unit; internal recovery
of the same job does not charge the user again, although execution cost and
attempts remain measured and bounded.

Admission checks quota and waiting capacity in the same transaction, using a
consistent lock order. Failure rolls back creation, charges, and associations.
No network call runs inside that transaction.

Before broader deployment, define and test a collection-creation quota, a global
waiting limit, and a per-user limit based on observed durations and provider
budget. Capacity refusals must be explicit and recoverable, without an unbounded
memory queue or lost intent. A separate polling limit remains future work; status
reads do not consume a creation quota.

## 7. Public responses and frontend recovery

Public conversion is implemented in
[collector_presenters.py](../backend/app/routes/collector_presenters.py), using
[collector_schemas.py](../backend/app/routes/collector_schemas.py). Existing error
codes include `collection_failed`, `collection_scheduling_failed`,
`collection_not_scheduled`, `classification_failed`, `classifier_vote_failed`,
and `validation_failed`. They do not yet implement all retry causes in section 5.
Presentation does not erase internal stored diagnostics.

Reading a job or embedding it in a classification response uses the same explicit
public fields: ID, public URL, state, outcome, useful counts, timestamps, and a
controlled diagnostic. Another user's origin `repository_candidate_id` is not
exposed. Raw exceptions and unfiltered external content do not become public
messages. Technical diagnostics remain in storage and logs with job/candidate IDs.

The latest owned repository analysis can be restored after reload. Candidates
reference jobs; the shared frontend job manager owns their current state. Polling
failure is distinct from collection failure. `classification_progress` exposes
saved/failed vote counts without model request snapshots or raw provider errors.

**Proposed:** a paginated endpoint covering all accessible requests and jobs, and
per-user retry eligibility with a reason and earliest retry time. A user's quota
must never become a global status on a shared job.

## 8. Durable execution and proposed leases

Both classification and collection already consume persisted PostgreSQL work
independently of HTTP request lifetime. A consumer claims a task only when it has
an execution slot. No model/HTTP call holds a persistence transaction open.

The future lease-based design adds:

1. Acknowledge accepted work only after persistence.
2. Persist acceptance and its collection intent atomically.
3. Claim a job when execution capacity is available; otherwise leave it pending.
4. Persist renewable ownership and an execution generation.
5. Recover expired ownership under a finite retry budget and total deadline;
   otherwise finish with an interruption diagnostic.
6. Check the current generation on all final writes, including errors, so an old
   worker cannot overwrite a newer execution.
7. Preserve the atomic datasets-plus-`done` transaction.

Per-vote attempt tokens already reject stale vote writes. They are not renewable
job leases or authorization for multiple API instances. Worker loss can still
repeat an external call, especially if its response was not committed. SQL
constraints and generation checks protect published results, not exactly-once
external execution. Recovery budgets, deadlines, and renewal cadence must be
specified and tested before introducing leases.

Until then, keep one application process and one instance. Startup preserves
queued/pending work and fails interrupted running work. Global startup recovery
would invalidate another process's tasks in a multi-instance deployment.

## 9. Verified implementation and remaining work

References name functions and files so they remain useful when line numbers move.

| Area | Current implementation | Remaining target |
| --- | --- | --- |
| Job access | Owner and association filters in [collection_jobs.py](../backend/app/db/collection_jobs.py), `get_collection_job_for_owner`. | Preserve access checks for future history and admission APIs. |
| Repeated classification | [collector.py](../backend/app/routes/collector.py), `classify_repository_result`, only reads follow-up for terminal decisions. | Separate versioned reevaluation if needed. |
| Acceptance transaction | [classification_completion.py](../backend/app/db/classification_completion.py), `complete_candidate_classification`, commits decision and reservation together. | Separate deferred-admission intent if introduced. |
| Partial votes | [classification_votes.py](../backend/app/db/classification_votes.py) stores validated responses, fingerprints, errors, and attempt tokens. | No automatic retry scheduler or job leases. |
| Collection retry | `retry_collection_job_for_owner` requeues an owned failed job; active retries are idempotent. Internal new-job retries can inherit compatible votes. | Stable command IDs, immutable collection-attempt history, and empty-result retries. |
| Validation diagnostics | [downloads.py](../collector/validation/downloads.py) and [main.py](../collector/main.py) retain validation states/reasons and failed-validation audit. | Reliable empty/incomplete outcome distinction before introducing cooldowns. |
| Public responses | [collector_presenters.py](../backend/app/routes/collector_presenters.py) sanitizes technical diagnostics consistently. | Structured retry eligibility and timing. |
| Quotas | [api_quotas.py](../backend/app/db/api_quotas.py) and [security.py](../backend/app/security.py) enforce existing request quotas. | Atomic collection-admission quota and waiting limits. |
| Consumers and restart | [workers.py](../backend/app/workers.py) bounds execution; [main.py](../backend/app/main.py) recovers startup state. | Renewable ownership, bounded automatic recovery, and multiple instances. |
| Collection finalization | [collection_completion.py](../backend/app/db/collection_completion.py) atomically saves datasets and completes the job. | Preserve rollback guarantees. |
| Frontend recovery | [Frontend job lifecycle](frontend-job-lifecycle.md) and `App.jsx` restore the latest analysis without resubmission. | Full paginated history. |

The original implementation batches were: document the contract; test and sanitize
public views; consider service extraction; add structured diagnostics and explicit
commands; add admission quotas/cooldowns; then leases and complete history.
Several correctness fixes were delivered before service extraction because it
was not necessary for them. Additional abstraction of `ensemble.py` is not part
of this work: parallel execution is already shared in `voting.py`, while the two
flows keep their distinct interpretation rules.

Future changes should preserve causes before extending commands, and establish
reliable empty outcomes before making them reusable under cooldown rules.

## 10. Acceptance scenarios

This list combines implemented guarantees and proposed tests. Rows explicitly
marked proposed are not claims of behavior or passing tests today.

| ID | Scenario | Expected result / status |
| --- | --- | --- |
| A01 | Alice and Bob concurrently request equivalent public collection for accepted candidates. | One active job and two authorized associations. |
| A02 | Charlie knows the job ID but has no association. | `404`, with no access to its contents. |
| A03 | Bob reads the shared job or receives it within classification output. | Same public view; no private Alice candidate or raw exception. |
| A04 | Two search contexts refer to the same URL. | Independent classifications; only equivalent collection work is shared. |
| A05 | A historical job has a matching URL but no proven association. | Migration grants no new readers. |
| C01 | Concurrent classification requests target one candidate. | One reserved execution; request quotas retain their defined semantics. |
| C02 | Accepted classification is submitted again after empty/failed collection. | No new job or model call. |
| C03 | Rejected classification is submitted again. | Existing decision; no collection. |
| C04 | Reservation or association fails during decision finalization. | Decision, new job, and association roll back together; retry reuses valid saved votes. |
| C05 | Collection-admission quota blocks an accepted candidate. | Proposed: keep acceptance and deferred intent; no fictitious failed job. |
| R01 | The same retry command is delivered again after its job finishes. | Proposed: return the same attempt through a stable command ID. |
| R02 | Authorized users concurrently retry equivalent failed work. | Current same-job retry queues one job; proposed new-attempt protocol preserves authorized associations. |
| R03 | A new candidate targets a still-valid reliable empty result. | Proposed: reuse it without work or extending its validity. |
| R04 | Processing version changes after a collector fix. | Proposed: do not reuse an older empty outcome as a new-version result. |
| R05 | A distribution times out and no alternative validates. | Validation failure is retained; proposed outcome is incomplete, not a reliable 24-hour empty result. |
| R06 | No resource qualifies and all necessary checks in scope complete. | Proposed: reliable empty outcome with reason and scope. |
| R07 | An old job is `done` without datasets or sufficient diagnostics. | Unknown outcome; migrations invent no cause. |
| R08 | Provider requires a delay, or network policy blocks the URL. | Respect the restriction; no automatic loop bypasses it. Provider-aware cooldown admission remains proposed. |
| Q01 | Concurrent connections admit equivalent new work. | Proposed: one collection-creation quota charge. |
| Q02 | Admission fails after charging but before creation finishes. | Proposed: roll back charge, job, and associations together. |
| Q03 | Alice exceeds her quota while Bob has capacity. | Proposed: defer Alice without globally blocking Bob's URL. Current request quotas are already owner-specific. |
| Q04 | User joins work, or a worker recovers the same job. | Proposed: no additional collection-creation charge. |
| Q05 | Waiting capacity is exhausted. | Proposed: explicit, recoverable refusal without unbounded memory queues. |
| E01 | Process stops after job commit but before claim. | Pending job resumes; interrupted running jobs become errors. |
| E02 | HTTP connection disappears after backend acceptance. | Durable task continues independently and persists its result. |
| E03 | Worker finishes after ownership expires and another takes over. | Proposed job leases reject stale results/errors; vote tokens already reject stale vote writes. |
| E04 | A dataset write fails during finalization. | Roll back all writes in that transaction; job does not become `done`. |
| E05 | Task recovery budget is exhausted. | Proposed: explicit terminal diagnostic without infinite retries. |
| F01 | User reloads or loses a classification response. | Restore the latest analysis without implicit retries; full history remains proposed. |
| F02 | User changes search or logs out during shared work. | Backend work continues; stale session responses cannot update the new session. |
| V01 | One model fails after two valid responses, including a negative vote. | Save both valid votes; explicit retry calls only the failed model. |
| V02 | Input or model/prompt configuration changes before retry. | Start a separate run and never mix incompatible votes. |
| V03 | Persistence of the final decision fails after all votes are saved. | Retry finalization without repeating the saved model calls. |

Locking, concurrent admission, quotas, and rollback tests use real PostgreSQL and
multiple connections with deliberate overlap. Mocks are suitable for public
conversion and orchestration, but do not prove SQL invariants. Interruption tests
exercise persistence boundaries and ownership tokens.

Existing coverage includes [test_collection_workflow.py](../tests/test_collection_workflow.py),
[test_classification_workflow.py](../tests/test_classification_workflow.py),
[test_vote_persistence.py](../tests/test_vote_persistence.py), and frontend
classification/job tests. Future admission, cooldown, command-ID, and lease tests
must accompany their implementation.

Historical verification records: public-response work passed 343 Python tests and
26 frontend tests; the three 2026-09-18 fixes passed 354 Python tests and 26 frontend
tests; persistent classification then passed 355 Python tests and 33 frontend
tests. Those runs used temporary PostgreSQL 16, excluded the container-firewall
integration test, and passed Ruff; the latter two also passed the frontend build.
These counts describe those historical revisions, not the current suite.

## Design references

- [OWASP — Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html): least privilege, per-access checks, and authorization relationships.
- [AWS — Timeouts, retries, and backoff with jitter](https://d1.awsstatic.com/builderslibrary/pdfs/timeouts-retries-and-backoff-with-jitter.pdf): bounded retries and multiplication across layers.
- [AWS — Transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html): atomically recording a change and intent for later work.
- [PostgreSQL — Locking clauses](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE): concurrent task claiming primitives, not a complete durable job system by themselves.

These references motivate mechanisms. Sharing policy, initial cooldown values,
and implementation order are project-specific choices.
