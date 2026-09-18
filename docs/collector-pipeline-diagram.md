# Collector Pipeline Diagram

> Current runtime flow, verified 2026-09-18.

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
    Load -->|already accepted or rejected| Existing["Return existing decision and follow-up; no new job"]
    Load -->|eligible for classification| Quota["Consume classification quota<br/>for eligible LLM work"]
    Quota --> Reserve["start_candidate_classification(..., owner_id)<br/>pending -> classifying"]
    Reserve --> Trusted["Rebuild RepositorySearchResult<br/>from PostgreSQL query + metadata"]
    Trusted --> LLM["Repository relevance classifier"]
    LLM --> Outcome{"Structured decision?"}
    Outcome -->|operational error| Error["Persist candidate=error<br/>HTTP 502; explicit retry required"]
    Outcome -->|rejected| Rejected["Persist rejected<br/>no collection job"]
    Outcome -->|accepted| Accepted["One transaction: decision + saved lookup or job + association"]
    Accepted --> Job["Commit before a collection worker can claim the job"]
```

The frontend cannot supply the URL, query, owner, or metadata used by the classifier.
The owner comes from the authenticated Bearer token, and every candidate read or
state transition verifies it through `search_sessions`; another owner receives
a not-found response.
Atomic state reservation prevents simultaneous LLM calls for one candidate.
React classifies at most two candidates concurrently and ignores responses whose
`search_id` no longer matches the active search.
Acceptance and job reservation use the same connection and transaction. A failure
to reserve or associate the job rolls back the decision too; retrying the
classification can repeat the LLM call. Network and LLM calls stay outside this
transaction. If the final decision and its follow-up cannot be persisted, the route
attempts to move the still-`classifying` candidate to `error` before returning
HTTP 500. That recovery write can also fail while PostgreSQL is unavailable.

Repository acceptance means relevance to the user query. It does not by itself
prove health relevance, source authority, licence acceptability, or file
availability.

## Automatic Collection

```mermaid
flowchart TD
    Candidate["Newly accepted repository candidate"] --> Reserve["Reserve on the decision transaction"]
    Reserve --> Saved{"Candidate URL already observed<br/>for a saved dataset?"}
    Saved -->|yes| Already["state=saved; no work"]
    Saved -->|no, pending/running job exists| Reuse["Associate candidate with active job; commit"]
    Saved -->|no active job| Pending["Create pending job and association; commit"]
    Pending --> Schedule["Available consumer polls PostgreSQL"]
    Schedule --> Running["claim_pending_collection_job()<br/>atomic pending to running"]
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
an exception is stored as job `error`. Repeating classification reads the same
associated job even after a terminal outcome. A newly accepted candidate at the
same URL can create another attempt if no dataset or active job exists. Old
terminal rows remain history; there is no public collection retry endpoint yet.

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
- Collections use a PostgreSQL queue: committed pending jobs are claimed only
  when a consumer has capacity, without an additional in-memory backlog.

On single-process startup, pending collection jobs survive and are consumed;
interrupted running jobs, searches, and candidate classifications become `error`.
Normal shutdown drains current collection work. Forced termination leaves running
jobs for startup recovery, without automatic retries. Use one API process and
one instance; classification itself still depends on the HTTP request lifecycle.
Static Bearer tokens, candidate ownership,
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
