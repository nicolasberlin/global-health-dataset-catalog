# Search progress polling

`GET /collector/searches/{search_id}/progress` returns `search_id`,
`polling_required`, and the existing public candidate `items`, including vote
progress, associated collections and saved dataset IDs. Authentication is the
same as other protected collector reads. Missing and foreign searches both
return 404. Responses are not cacheable and never enqueue work or consume work
quotas. The existing individual read and retry endpoints remain compatible.

The database uses a short read-only REPEATABLE READ transaction with five SELECTs
regardless of candidate count. A collection is selected through the candidate's
explicit job association, not through URL equality. Existing datasets are used
only when the accepted candidate has no associated job, matching individual reads.

Polling continues while the search runs, a classification is queued/classifying,
or an associated collection is pending/running. An unrequested legacy candidate
alone does not keep polling alive. Failed and empty outcomes stop polling.

The frontend keeps one loop per search per mounted session, including searches
no longer displayed. Normal polls wait two seconds after the previous response;
requests do not overlap. Errors back off to thirty seconds; Retry-After takes
precedence. Unauthorized, forbidden and missing searches stop their loop.
Session changes cancel all requests and invalidate late responses. Retrying a
shared job invalidates snapshots and resumes all locally tracked searches that
reference it. A lost POST acknowledgement triggers a read, never an automatic
repeat of the command. Returning to a visible tab refreshes tracked searches,
including stopped ones, to discover external retries. A full reload still
restores only the existing latest-analysis endpoint's selection.

Snapshots remain search-scoped, so responses for shared jobs cannot overwrite
another search's state. Vote counters are accepted even when updated_at is
unchanged. Catalog refresh notifications are deduplicated per saved job.

No schema, authentication, worker, model, proxy or quota configuration changes
are required. Ten simultaneous classification polls previously approached 14
requests/second ignoring latency; one grouped loop approaches 0.5. Response size
still grows with candidate count, and catalog/detail reads are additional traffic.
