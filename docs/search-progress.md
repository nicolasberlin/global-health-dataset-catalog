# Search progress polling

`GET /collector/searches/{search_id}/progress` returns `search_id`,
`polling_required`, the execution/outcome fields documented in
[Pipeline outcomes](pipeline-outcomes.md), and the existing public candidate `items`, including vote
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

The frontend keeps one loop per followed search per mounted session. Starting a
new search stops old loops and aborts their in-flight reads, without cancelling
server-side work. Normal polls wait two seconds after the previous response;
requests do not overlap. Each progress request has a fifteen-second deadline,
including response parsing. Three consecutive failures stop automatic tracking;
the first two failures wait four and eight seconds, with Retry-After taking
precedence. A valid response resets the failure counter. The interface shows
that the collection status is unknown and offers Resume tracking, which starts
fresh GET attempts without submitting any work. Unauthorized, forbidden and
missing searches stop immediately with the existing access error.
Session changes cancel requests and invalidate late responses. Retrying a shared
job invalidates snapshots for locally tracked searches that reference it, but
cannot reactivate old loops stopped by a new search or the failure limit.
A lost POST acknowledgement triggers a read, never an automatic repeat of the
command. Returning to a visible tab refreshes eligible tracked searches to
discover external retries, but does not revive stopped or inaccessible loops.
Explicit restoration or Resume tracking can restart failure-limited tracking.
A full reload still restores only the latest-analysis endpoint's selection.

Snapshots remain search-scoped, so responses for shared jobs cannot overwrite
another search's state. Vote counters are accepted even when updated_at is
unchanged. Catalog refresh notifications are deduplicated per saved job.

The original grouped-polling implementation needed no configuration changes.
The additive outcome contract now requires schema migration 7; authentication,
worker concurrency, model, proxy and quota settings are unchanged. Ten simultaneous classification polls previously approached 14
requests/second ignoring latency; one grouped loop approaches 0.5. Response size
still grows with candidate count, and catalog/detail reads are additional traffic.
