# Collector Pipeline Diagram

> Current runtime flow, verified 2026-09-08.

Repository search persists searches and candidates for trusted classification.
Only the collection pipeline can create or update catalogue datasets.

## Repository Search

```mermaid
flowchart TD
    Query["Original user query + Bearer token"] --> Auth["Authenticate owner"]
    Auth --> Quota["Consume search quota"]
    Quota --> Session["create_search_session(query, owner_id)"]
    Session --> Normalize["Normalize for local search only"]
    Normalize --> Local["PostgreSQL english full-text search"]
    Local --> Match{"Local result?"}
    Match -->|yes| LocalDone["Complete session: database/completed"]
    LocalDone --> LocalUI["Return search_id + saved datasets"]
    Match -->|no| DataCite["search_repository_metadata(original query)"]
    DataCite --> Bound["Filter and bound provider metadata"]
    Bound --> Persist["Persist repository_candidates and<br/>complete session in one transaction"]
    Persist --> OnlineUI["Return search_id + candidate_id values"]
```

The local normalizer never changes the query stored in `search_sessions` or
sent to DataCite and the LLM. Provider failure completes the search as `error`;
warnings produce `partial`. A candidate batch and its successful session
completion commit atomically. After a session is created, failures while
completing a local result or bounding and persisting external candidates also
attempt to close the session as `error`.

## Candidate Classification

```mermaid
flowchart TD
    UI["POST /repository-candidates/{candidate_id}/classify<br/>Bearer token; empty body"]
    UI --> Load["get_repository_candidate(candidate_id, owner_id)"]
    Load --> Quota["Consume classification quota<br/>for eligible LLM work"]
    Quota --> Reserve["start_candidate_classification(..., owner_id)<br/>pending -> classifying"]
    Reserve --> Trusted["Rebuild RepositorySearchResult<br/>from PostgreSQL query + metadata"]
    Trusted --> LLM["Repository relevance classifier"]
    LLM --> Outcome{"Structured decision?"}
    Outcome -->|operational error| Error["Persist candidate=error<br/>HTTP 502; explicit retry required"]
    Outcome -->|rejected| Rejected["Persist rejected<br/>no collection job"]
    Outcome -->|accepted| Accepted["Persist accepted"]
    Accepted --> Job["Reserve or reuse job by candidate_id"]
```

The frontend cannot supply the URL, query, owner, or metadata used by the classifier.
The owner comes from the authenticated Bearer token, and every candidate read or
state transition verifies it through `search_sessions`; another owner receives
a not-found response.
Atomic state reservation prevents simultaneous LLM calls for one candidate.
React classifies at most two candidates concurrently and ignores responses whose
`search_id` no longer matches the active search.
If the final accepted or rejected decision cannot be persisted, the route
attempts to move the still-`classifying` candidate to `error` before returning
HTTP 500. That recovery write can also fail while PostgreSQL is unavailable.

Repository acceptance means relevance to the user query. It does not by itself
prove health relevance, source authority, licence acceptability, or file
availability.

## Automatic Collection

```mermaid
flowchart TD
    Candidate["Accepted repository candidate"] --> Reserve["reserve_repository_candidate_collection_job(candidate_id, owner_id)"]
    Reserve --> Saved{"Candidate URL already observed<br/>for a saved dataset?"}
    Saved -->|yes| Already["state=saved; no work"]
    Saved -->|no, pending/running job exists| Reuse["Reuse active job"]
    Saved -->|no active job| Pending["Create new pending job"]
    Pending --> Schedule["_schedule_collection_job()<br/>FastAPI background task"]
    Schedule --> Running["mark_collection_job_running()"]
    Running --> CandidateCollect["collect_repository_candidate_with_report()"]
    CandidateCollect --> Page["Fetch one landing page + page classification"]
    Page --> Distribution["Bounded distribution validation"]
    Distribution --> Eligible{"Page accepted and<br/>valid distribution exists?"}
    Eligible -->|yes| Result["Add dataset to CollectionResult"]
    Eligible -->|no| EmptyResult["CollectionResult without dataset"]
    Result --> Complete["complete_collection_job()"]
    EmptyResult --> Complete
    Complete --> Done["Atomic datasets + job done commit"]
```

DataCite metadata is not copied into `collected_datasets`. The collector fetches
the candidate landing page and applies the existing page and file gates. A done
job with `saved_count=0` is shown as collection completed without a valid file;
an exception is stored as job `error`. A later accepted request creates a new
attempt after either terminal outcome if the dataset is still absent. The old
terminal row is retained as attempt history.

## Collection Entry Point

The website starts collection automatically for accepted repository candidates.
Source administration and manual source collection have been removed from the
website, including the former `POST /collector/collection-jobs` endpoint.
The source discovery library remains available for maintenance outside the UI.

## Limits And Execution

- DataCite returns at most 10 candidates per query.
- React and the backend executor allow at most two candidate classifications at
  once.
- Collection concurrency defaults to two jobs per backend process.
- Source page and distribution limits come from `CollectorConfig`; repository
  collection is additionally restricted to one landing page.
- HTML, JSON, sitemap, and distribution reads are bounded and all redirects are
  revalidated by `open_public_http_url()`.
- Background work is process-local, not a durable queue. `_schedule_collection_job()`
  is the single scheduling point intended for a future queue replacement.

On single-process startup, interrupted searches, jobs, and candidate
classifications are marked `error`. Static Bearer tokens, candidate ownership,
and persistent per-owner quotas are implemented for the MVP. OAuth/OIDC, roles,
multi-worker job ownership, and infrastructure-level traffic limits remain
future production work.

## Final Save Condition

```text
repository candidate accepted (for automatic collection only)
AND page classifier accepted=true
AND at least one considered distribution validates successfully
THEN the dataset enters CollectionResult
AND complete_collection_job() atomically upserts it and marks the job done
```

See [Classification Architecture](classification-architecture.md) for prompts
and [Database Schema](database-schema-diagram.md) for persisted state.
