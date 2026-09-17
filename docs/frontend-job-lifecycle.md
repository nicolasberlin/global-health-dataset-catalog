# Search, collection jobs, and catalog lifecycle

The frontend now separates state by lifetime. These choices implement the four
review points without adding a new state-management dependency.

1. **Job authorization.** `GET /collector/collection-jobs/{id}` uses
   `principal.owner_id` and requires an explicit association through
   `collection_job_candidates`, the candidate, and its search session. Job
   reservation records each association transactionally, including reuse of a
   job for another user's accepted candidate. A matching URL alone grants no
   access. Missing and inaccessible jobs both return 404. Internal workers can
   still read jobs without a user principal through the separate internal DB API.

2. **One job status.** `useCollectionJobs` is instantiated once in `App`, above
   both views. Candidates store only `jobId`; their displayed collection status
   is derived from the shared manager. It maintains at most one polling loop per
   job, ignores duplicate registrations, and emits one catalog refresh per
   successfully saved job. Terminal status cannot regress on a late registration.
   A hook at the existing application root is sufficient; a context provider
   would be useful if independent nested components needed direct job access.
   Transient tracking failures preserve server status and retry with backoff.
   401/403/404 stop polling and display unavailable tracking, not a failed job.

3. **Search and session isolation.** `useApiSession` creates a new session object
   when the token changes or is removed, aborts the old session's requests, and
   makes its responses ineligible for state updates. `requestJson` captures the
   request's token and checks cancellation again after parsing JSON. `runId` and
   `searchId` independently prevent an old search from modifying the visible one.
   A different query can replace a search during analysis. Queued classification
   work stops; already dispatched classifications may finish and register their
   jobs if the session is still current. Those responses cannot replace the new
   search. Logout also clears private results and loading indicators.

4. **Catalog refresh ordering.** `useDatasetCatalog` coalesces nearby refreshes
   and allows only one request in flight. An invalidation during that request
   marks its result obsolete and schedules one follow-up read. Failed refreshes
   retain the last successful data, and the view displays the error alongside
   the existing cards. Catalog reads remain public, as in the current backend.

Schema version 2 is applied by backend initialization. It preserves existing
rows and backfills only the original candidate association for historical jobs;
other historical sharing relationships were never persisted. It does not infer
new access rights from matching URLs.

This change covers mounted-application tracking. Recovering jobs after a full
page reload or a lost classification response still requires a backend listing
endpoint. Durable execution across backend restarts still requires worker
orchestration; React state and status recovery cannot supply that guarantee.

Regression coverage includes shared access and migration in PostgreSQL; a shared
job completing after navigation/search replacement; late classification and
JSON responses; token replacement/logout; retry after network failure; duplicate
terminal notifications; and catalog invalidations during a pending request.
