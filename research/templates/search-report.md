# Search diagnostic report — [query]

> Blank template, not a test result. Replace bracketed fields.
> Follow the [investigation guide](../search-diagnostics.md) for evidence rules.

## Main finding

[State the observed result, the main established blocker and its effect on the
user. Identify causes that remain unknown.]

## Context and objective

| Field | Value |
| --- | --- |
| Search and attempt | [search_id, attempt] |
| Exact query | [text] |
| Time and timezone | [start, end, Europe/Zurich] |
| Environment | [local / test / production] |
| API/client revisions | [versions actually executed, local changes] |
| Models and parameters | [versions, limits, timeouts, filters] |
| Associated trace | [path to search-trace.json] |
| Evidence coverage | [complete / partial / unknown; missing evidence] |

**Expected result:** [What the search should find and collect; known reference
records, if available.]

**Success criteria:** [Relevance, access, validation, persistence and acceptable
duration. State whether criteria were defined before execution.]

## Observed result

| Measure | Value | Evidence |
| --- | --- | --- |
| Local results | [count or unknown] | [evidence_id] |
| External candidates | [count or unknown] | [evidence_id] |
| Accepted / rejected / failed / pending candidates | [counts] | [evidence_id] |
| Distinct saved datasets | [count, IDs] | [evidence_id] |
| End-to-end duration | [duration or unknown] | [evidence_id] |
| Server state and overall outcome | [observed values] | [evidence_id] |
| Client tracking state | [state, last success, reason for stopping] | [evidence_id] |

Accepted candidates are not saved datasets. Deduplicate shared jobs and dataset
IDs. Discovery duration excludes the subsequent classification and collection.

## Stage analysis

Use the guide's statuses: `not_run`, `running`, `succeeded`, `empty`, `rejected`,
`failed` or `unknown`. An empty result requires evidence of completed execution.

| Stage | Observation | Status | Evidence | Limits / explanation |
| --- | --- | --- | --- | --- |
| Local search | [result] | [status] | [IDs] | [text] |
| External discovery | [sources, queries, filters, limits, results] | [status] | [IDs] | [text] |
| Model classification | [votes, decisions, errors, attempts] | [status] | [IDs] | [text] |
| Collection and extraction | [initial/final URL, HTTP, method, links] | [status] | [IDs] | [text] |
| Resource validation | [attempts, formats, checks, failures] | [status] | [IDs] | [text] |
| Persistence | [IDs, database outcome] | [status] | [IDs] | [text] |

## Significant candidates

Repeat for each useful failure, false positive or success:

- **Candidate/job:** [IDs, title, public URL, DOI].
- **Expected behavior:** [Reason to accept, reject or collect].
- **Model votes:** [Per model: decision, returned reason, attempt, diagnostics;
  distinguish repository relevance from page acceptance].
- **Page access:** [Initial/final URL, HTTP, MIME, duration, evidence].
- **Extraction:** [Method, found/excluded links and reasons].
- **Resources:** [Public URL, declared/detected format, whether access was
  attempted, checks, result and specific reason].
- **Persistence:** [Saved dataset ID or reason it was not saved].
- **Conclusion:** [Confirmed cause / hypothesis / undetermined; evidence].

## Findings and causes

| ID | Observation | Proposed cause | Confidence | Evidence | Missing verification |
| --- | --- | --- | --- | --- | --- |
| F1 | [observable fact] | [cause or unknown] | [confirmed / hypothesis / undetermined] | [IDs] | [targeted check] |

Date evidence and identify its revision. A current reproduction alone does not
establish the cause of an earlier execution.

## Proposed corrections

| Priority | Action | Finding | Expected result | Acceptance check |
| --- | --- | --- | --- | --- |
| [high/medium/low] | [specific change] | [F1] | [behavior] | [reproducible check] |

Distinguish collector fixes, improved diagnostics and interface wording.
A proposed action is not an implemented correction.

## Verification after a correction

[Complete after implementation, or state "not performed".]

| Revision/search | Scenario | Before | After | Verdict and evidence |
| --- | --- | --- | --- | --- |
| [commit, search_id] | [same input / controlled fixture] | [result] | [result] | [IDs] |

Record real network/model calls and changed parameters. A manual retry is a new
attempt; keep the original evidence for comparison.

## Appendices and limits

- [Links to API snapshots, redacted log excerpts and relevant fixtures].
- [Unavailable evidence and the conclusions it prevents].
- [Redactions applied; exclude credentials, cookies and raw medical content].
