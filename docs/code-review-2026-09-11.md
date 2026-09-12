# Code Review and Recommended Roadmap

> Review date: 2026-09-11  
> Scope: repository search, three-model classification, collection, validation,
> persistence, frontend tracking, maintainability, and production readiness.

## Executive Assessment

The project has a coherent MVP pipeline and several strong controls: server-side
candidate ownership, bounded public-network requests, redirect revalidation,
parameterized SQL, atomic dataset/job completion, and a strict three-response LLM
quorum. It is suitable for local development and controlled demonstrations.

It is not ready for untrusted public traffic yet. Two authorization/quota defects
allow information disclosure or unmetered work, and several correctness defects can
publish a resource as available when it is empty, restricted, or not the advertised
format. The browser and one FastAPI process also own work that must become durable
before restarts or multiple backend instances are supported.

## Confirmed Defects

### P0. Collection-job status is not scoped to its owner

`GET /collector/collection-jobs/{job_id}` authenticates a principal but discards it,
then loads the row only by its sequential integer ID
([route](../backend/app/routes/collector.py#L104),
[query](../backend/app/db/collection_jobs.py#L338)). An authenticated user can guess
another user's job ID and read its source URL, candidate ID, counters, and raw error.

**Fix:** associate every job with an owner, or join candidate jobs through
`repository_candidates -> search_sessions`, and include the owner in every read and
state transition. Return 404 for a job outside the caller's scope. Add an API test
with two owners.

### P0. Accepted candidates can create unlimited unmetered collection attempts

The classification quota is charged only for a pending candidate or an explicit
classification retry ([route](../backend/app/routes/collector.py#L275)). A request for
an already accepted candidate skips classification but still reserves collection
([route](../backend/app/routes/collector.py#L298)). The reservation only reuses
`pending` or `running` jobs, so every request after an `empty` or `error` attempt can
insert another job ([reservation](../backend/app/db/collection_jobs.py#L121)). Each
new job may fetch the page, call all three page classifiers, and validate a link.

**Fix:** return the last terminal collection state by default. Require an explicit
collection-retry operation, apply a collection quota, cooldown, and maximum attempt
count, and make the retry reservation idempotent.

### P1. An HTTP 200 HTML login page is accepted for an API link

Distribution validation rejects `text/html` only when the discovered format is not
`API` ([validator](../collector/validation/downloads.py#L46)). An API URL returning a
login page with HTTP 200 therefore produces `ok=True`, `format="API"`, and no error.
The catalogue can present a restricted page as an available data resource.

**Fix:** HTML must never mean confirmed data availability. Return a typed state such
as `restricted` or `unconfirmed` when a login/access page is detected. If the current
boolean contract is kept temporarily, return `ok=False` for HTML regardless of the
initial format. Add a login-page test.

### P1. HTTP validation accepts responses without usable data

The current decision accepts any non-HTML response from HTTP 200 through 399
([validator](../collector/validation/downloads.py#L51)). Confirmed examples include
`204 No Content` and a CSV URL returning JSON such as an authentication error. An
extension can also keep the inferred format despite a conflicting MIME type.

**Fix:** reject bodyless success statuses, check the sample against the claimed
format, identify common structured error envelopes, and represent ambiguity as
`unconfirmed`. Test 204/205, empty bodies, format/MIME conflicts, JSON errors, login
pages, and valid file/API samples.

### P1. Supplied network configuration is not applied by the pipeline

`CollectorConfig` exposes a timeout, sample limit, and user agent
([configuration](../collector/config.py#L7)), but the pipeline invokes the injected
fetcher with only a URL ([HTML call](../collector/main.py#L182)) and the validator with
only a distribution ([validation call](../collector/main.py#L297)). The default
fetcher and validator consequently use module-level defaults. A caller can change
page/distribution counts, while its network timeout, sample size, and user agent are
silently ignored.

**Fix:** build a configured `CollectorRuntime` or dependency object once and pass its
fetch, discovery, validation, and classification operations through the pipeline.
Add a test that captures the effective timeout, byte limit, and user agent from a
custom configuration.

### P1. Partial-content size is wrong and the database field can overflow

When `HEAD` falls back to a ranged `GET`, the validator replaces the HEAD probe and
reads `Content-Length` from the 206 response. That value is normally the sample size,
not the full resource size ([fallback](../collector/validation/downloads.py#L35)). It
does not parse the total from `Content-Range`. The database stores the result in an
`INTEGER`, so a legitimate resource larger than 2,147,483,647 bytes can also fail the
transaction.

**Fix:** prefer a credible HEAD size or parse the `/total` portion of
`Content-Range`, validate bounds, and migrate `validation_size_bytes` to `BIGINT`.
Test 206 samples and resources above 2 GiB.

### P1. A new search abandons tracking of earlier active collections

The UI enables another search when repository candidates are no longer pending or
classifying; it does not include collection jobs in that condition
([state](../frontend/src/App.jsx#L566)). Starting a new run invalidates the old run ID,
which stops its collection poll ([poll](../frontend/src/App.jsx#L193)). The backend
job may finish successfully, but the in-memory catalogue remains stale until another
refresh.

**Fix:** track active jobs independently from the current search run and resume them
by job/search ID after navigation or reload. Do not mark a tracking timeout as a
backend job failure.

### P1. Redirected candidates may not enrich their result card after collection

The frontend associates a saved dataset with a repository candidate by comparing
dataset URLs. Collection can replace a DOI or redirect URL with the final canonical
dataset URL, while preserving the original candidate only as `source_url`. The saved
dataset then exists but its candidate card can continue to show unconfirmed access.

**Fix:** return the saved dataset ID and canonical URL as part of job completion and
link them explicitly. Matching `source_url` is a useful interim fallback. Add a DOI
redirect-to-canonical integration test.

## Architecture Risks and Refactoring Opportunities

1. **Move workflow ownership to the backend.** React currently dispatches every
   classification. Closing the tab leaves undispatched candidates pending. A durable
   backend workflow should own search, classification, collection, and resumable
   status; React should render it.
2. **Replace process-local tasks.** `BackgroundTasks` and both thread pools disappear
   on restart. Use leases, heartbeats, bounded queue capacity, idempotency, retry with
   backoff, cancellation, and dead-letter handling. A job should remain `pending`
   until a worker actually acquires it.
3. **Pair distributions with their evidence.** Replace parallel `distributions` and
   `validation_results` lists with a `ValidatedDistribution` aggregate. This removes
   the URL/format join that caused the earlier `API -> JSON` orphan mismatch.
4. **Keep partial successes.** Represent each page with a typed outcome such as
   `accepted`, `semantic_rejection`, `no_distribution`, `validation_failure`, or
   `operational_error`. One failed page should not discard earlier successful pages.
5. **Fetch when structured links are absent.** A structured candidate with only a
   title currently skips landing-page discovery, consumes three model calls, then
   fails because it has no distribution. Skip HTML only when usable distribution
   metadata is already present.
6. **Paginate and filter in PostgreSQL.** The catalogue endpoint loads every dataset
   and every distribution into memory ([query](../backend/app/db/collected_datasets.py#L82)).
   Add cursor pagination, a bounded limit, server-side filtering/sorting, and a
   dataset-detail endpoint.
7. **Validate the database schema once.** Startup already validates the schema, yet
   repository functions repeatedly query its version. Remove the per-operation
   checks after successful startup and adopt data-preserving migrations.
8. **Bound provider responses.** The LLM client calls `response.read()` without a
   byte limit ([client](../collector/classification/llm_client.py#L105)). Add a
   response limit and bounded reason/evidence fields, plus transient retry metrics.
9. **Split the orchestrators.** Extract backend search, classification, and
   collection services from `collector.py`. Extract the API client and search/catalog
   hooks from `App.jsx`. Keep run-ID guards until job tracking is durable because they
   prevent stale asynchronous responses from overwriting a newer search.
10. **Type and centralize the ensemble policy.** Replace positional model tuples with
    `ModelSpec`, share RCP client construction and voting execution, and return the
    voting policy to the UI instead of hard-coding `2/3`, `3/3`, and total `3`.
11. **Remove dormant source administration if the product decision is final.** The UI
    no longer exposes it, but source routes, tables, seeds, quotas, and job variants
    remain. Remove the full subsystem through a migration once confirmed; keep the
    reusable discovery adapters.

## Deliberate Policies to Revisit

These are current choices rather than isolated implementation bugs:

- local-first search stops external discovery as soon as one PostgreSQL result exists;
- `somewhat_relevant` counts as accepted and starts collection;
- a 2/3 positive threshold still requires all three models to return usable replies;
- only one distribution is tested per dataset by default, so a broken first link can
  hide a valid second link;
- failed validation evidence is discarded and saved links are not revalidated;
- technical collection success currently makes a dataset visible without a separate
  reviewed/published state.

Each policy needs an explicit product decision and a measured evaluation set before
public launch.

## Recommended Delivery Order

### Phase 0 - Public-exposure blockers

1. Fix job ownership, collection retry/quota bypass, and public error redaction.
2. Fix validation false positives, configuration propagation, and file-size storage.
3. Enforce HTTPS, private PostgreSQL access, restricted egress, secret management,
   and a CI gate that includes PostgreSQL integration tests.
4. Define `candidate`, `collected`, `reviewed`, `published`, `stale`, and `withdrawn`
   states plus authority, licence, provenance, and sensitivity policy.

### Phase 1 - Durable operation

1. Move the complete workflow into a durable backend worker.
2. Add real migrations, automated backups, and tested restore/rollback.
3. Add readiness checks, structured logs, metrics, alerts, and bounded queues.
4. Make frontend tracking resumable and link a job to its saved dataset explicitly.

### Phase 2 - Data quality

1. Persist DOI, licence, version, provider provenance, and candidate-to-dataset links.
2. Add semantic duplicate detection and scheduled link revalidation with history.
3. Build labeled evaluation sets for repository relevance and page eligibility, then
   set `somewhat_relevant`, quorum, and fallback policies from measured results.
4. Benchmark additional repository providers before enabling them.

### Phase 3 - Product and scale

1. Add local-plus-external search controls, pagination, server-side filters, sorting,
   permanent detail URLs, and search restoration after reload.
2. Add institutional authentication and curator roles where human review is needed.
3. Pin reproducible builds, add staging and rollback, define capacity/cost budgets,
   and run disaster-recovery exercises.

The actionable version of this plan is maintained in [`TODO.txt`](../TODO.txt).
