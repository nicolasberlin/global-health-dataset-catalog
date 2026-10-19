# Collection reference

Read this when changing collection behavior, investigating an incomplete search,
or enabling browser recovery. To run a first search, start with the
[README](../../README.md); for HTTP requests, use [API integration](../api-integration.md).
The catalogue stores metadata, provenance and validated resource links. It does
not download or preserve complete datasets.

## Pipeline and fallback

Search checks the local catalogue before discovering repository candidates through
DataCite. Each candidate is classified against the original query. Accepted
candidates receive a persisted collection job, which resolves that record,
classifies its dataset/health eligibility, validates resource access, then saves
the metadata and links atomically with job completion.

Both classification stages use three configured voters and require three usable
responses with at least two positive votes. Two positive votes plus a technical
failure are insufficient. Page classification uses the selected record's evidence;
it does not repeat the query-relevance decision.

Record resolution tries these permitted methods in order:

1. The official API through a recognized, configured connector.
2. The same record's HTML if the API cannot supply a validated resource.
3. A disposable browser session, only when enabled for that host.

An authoritative empty API inventory stops navigation. A missing or malformed
inventory is a failure, not evidence that no files exist. A valid semantic
rejection also stops collection: fallback never seeks a different model decision.
Failed methods remain in history after successful recovery.

Methods share the attempt deadline and resource-check state. Defaults allow at
most three checks and one saved validated distribution per record. Resources are
ranked and deduplicated; a failed HTTP resource can be checked again in a browser
session, consuming the same check allowance. Coverage reports discovered, checked,
validated and limited resources, without claiming exhaustive repository coverage.

Dataverse, Zenodo, Figshare, Dryad, InvenioRDM and DSpace 7+ are record connectors,
not additional search crawlers. CKAN, Socrata and `data.json` source discovery is
a separate entry path sharing extraction, page classification and validation.
See [connector contracts](collection-connectors.md) for supported URLs, host/API
configuration and repository-specific version rules.

## Identity and provenance

A file reference resolves that file, not every file in its parent dataset. Native
IDs, persistent IDs, versions, DOI/URL identity and local relationships constrain
the selected record. A requested version is never silently replaced by the latest
version. Version-pinned Dataverse dataset pages use HTML/browser rather than its
default latest-version API.

API identity survives HTML recovery. Without established API identity, only facts
proven by the original reference are retained. A parent's citation DOI is not
assigned to a file. Fallback links stay within the connector's supported record
scope. Catalogue rows remain unique by URL; `record_identity` does not merge DOIs
automatically or implement complete version tracking.

HTML/JSON-LD selection uses IDs, DOI/URLs and local `@id` relationships, including
an embedded `WebPage.mainEntity`. If several Dataset entities remain ambiguous,
uncertain metadata stays empty and files are not arbitrarily assigned. Site-level
or nested-organization metadata cannot replace the selected Dataset's licence,
dates or geography. Titles, classification text, distributions and demographic or
disease signals stay within the selected entity's scope.

Provenance records ambiguity and prevents later enrichment from refilling those
uncertain fields. Bounded raw JSON-LD remains internal evidence, separate from the
selected entity. Remote contexts are never downloaded. CKAN, Socrata and
`data.json` provenance identifies the effective API/catalogue URL actually read;
relative references use that final document URL, including redirects. Supported
Dataset type IRIs and local `@id` URL objects do not require general RDF expansion.

## Extraction limits

Limits apply during construction/traversal, not just after parsing:

| Evidence | Default internal limit |
| --- | --- |
| HTML text / retained evidence | 1,000,000 characters each |
| HTML depth / nodes / links | 128 / 20,000 / 2,000 |
| DOM path / attribute text | 1,024 / 16,384 characters |
| JSON-LD text across scripts | 262,144 characters |
| JSON-LD depth / nodes / scripts | 64 / 20,000 / 32 |

Void HTML elements do not grow the parser stack. JSON-LD depth is checked before
decoding; local-reference expansion is bounded separately. Traversals check the
attempt deadline/cancellation, and page classification bounds prompt fields and
distribution count. Extraction and classification reuse one parsed page snapshot.

Expected parse errors, unknown response charsets and excessive nesting become
controlled failures. Exceeding a limit abandons that method and tries the next
permitted fallback. Without recovery, the result is incomplete, not a semantic
rejection. The implementation lives in
[extraction limits](../../collector/extraction/limits.py) and the
[shared pipeline](../../collector/collection/pipeline.py).

## Resource validation and Socrata

An advertised URL, extension or HTTP 200 alone does not establish valid access.
Validation combines response metadata with a bounded GET sample, normally up to
65,536 bytes. Sample evidence can refine the reported format. PDF publications,
images and HTML are excluded from eligible resources; insufficient sample
evidence remains unconfirmed. A ZIP sample does not prove that the whole archive
is intact or contains a valid workbook.

| Access status | Meaning |
| --- | --- |
| `available` | A sampled data response was confirmed and is eligible for retention. |
| `unavailable` | The resource is conclusively missing/unavailable. |
| `restricted` | Access needs permission or an unsupported authenticated flow. |
| `unconfirmed` | Network/content evidence cannot confirm a valid data response. |

A failed alternative does not invalidate another proven distribution. Without a
proven distribution, restricted/unconfirmed checks are inconclusive. Dataset
semantic acceptance and access validation are separate decisions.

Socrata CSV/JSON distributions expose a paginated SODA API rather than a complete
file export. Links begin with `$limit=1000`, `$offset=0`, `$order=:id`. Persisted
signals include `api_endpoint`, `paginated`, `complete_export=false` and pagination
instructions: advance the offset by 1,000 with stable ordering until an empty
page is returned. Collection validates a bounded sample, not every page. A
complete export is unnecessary; no separate one-row distribution is generated.

## Attempt budget

`COLLECTION_MAX_DURATION_SECONDS` defaults to 300 seconds per claimed collection
attempt and accepts finite values from 1 to 3,600, including fractions. Invalid
values fail backend startup. Direct Python callers use
`CollectorConfig.collection_max_duration_seconds`; the environment variable
configures backend admission/claims.

Record metadata reads, HTML/browser work, page votes and probes share this budget.
Queue waiting, initial search discovery and repository relevance classification
are outside it. A job with multiple attempts can take longer than five minutes.
The UTC deadline is persisted on claim, then converted to a monotonic deadline
for execution, including voter threads. Keep host and PostgreSQL clocks aligned.

A newly scheduled automatic retry round clears the old deadline and gets a fresh
one on its next claim. Scheduling is refused if the current attempt has already
expired. A provider due time may exceed the old deadline; the independent LLM
retry-start window still applies and is not reset. Recovering the same
acquisition, replaying a command or acknowledging active work does not extend its
deadline, even after a configuration change. Explicit retries start a newly
admitted cycle.

Built-in HTTP transports use absolute request deadlines across connect/TLS,
status lines, headers, chunk framing and body reads. Public redirects share that
window; trickled bytes cannot renew it. Shorter request timeouts and byte caps
still apply. SSRF protection, validated destination addresses and TLS hostname
checks remain enforced. Authenticated model/browser control calls reject redirects.

DNS waits share the request and collection deadline. Four process-wide daemon
threads handle at most four admitted lookups; a late answer never connects. An
OS lookup cannot be forcibly interrupted, so four stuck calls exhaust resolution
capacity until they finish or the process restarts.
Injected callbacks/transports must bound their own blocking work. A worker keeps
its slot until operations and voter threads return; this is not a forced process
kill exactly at 300 seconds. Browser child processes have a separate service lease.

Persistence-only retries and final saves may continue after expiry. Complete
validated model responses remain eligible for checkpointing; incomplete responses
do not become successful votes. No subsequent external operation starts late.
Budget expiry reports `collection_budget_exhausted` and an incomplete outcome.
Already validated datasets/distributions remain eligible for the final atomic
save, including when a later probe expires. Unverified/interrupted resources are
never retained. This does not add general per-page recovery for unrelated fatal
exceptions in legacy multi-page source collection.

## Model retries and checkpoints

Repository and page classification use the same durable vote store and policy:

| Environment setting | Default | Constraint / purpose |
| --- | --- | --- |
| `LLM_MAX_ATTEMPTS` | `3` | 1–10 total calls per failed vote/cycle for transient failures |
| `LLM_INVALID_MAX_ATTEMPTS` | `2` | 1–`LLM_MAX_ATTEMPTS` total calls for invalid responses |
| `LLM_RETRY_WINDOW_SECONDS` | `120` | 1–3,600 seconds from first claim within which retries may start |

Invalid policy settings fail startup. Limits include the initial invocation.
Direct backend execution caps the default
invalid-response limit at the transient limit; Compose supplies both defaults
explicitly. Set both attempt limits to 1 to disable automatic retries. An explicit
retry begins a new cycle under existing admission quotas, without a lifetime cap
on user-authorized cycles.

Timeouts, network failures, provider 429 and temporary unavailability are
retryable. The first automatic pause is 2–2.5 seconds, subsequent pauses 5–6.25
seconds. A later provider `Retry-After` takes precedence and is never shortened.
If the next due date reaches or exceeds the retry window, processing ends incomplete. A
queued retry claimed after the window cannot invoke a failed model again
automatically. This window limits retry starts, not an in-flight request's
duration; request timeouts and the collection attempt budget still apply.

Authentication/configuration errors, oversized responses and unrelated pipeline
failures do not receive automatic LLM retries. If any required failed vote is not
retryable, the ensemble stops. Technical failure never becomes a negative health
vote or conclusive empty result. Model redirects report `llm_configuration_error`;
configure the direct endpoint. Malformed/excessively nested JSON reports
`llm_invalid_response` and follows its bounded retry policy.

Validated votes, including negative votes, are reused only for the same input,
model configuration and prompt fingerprint. Only failed votes are recalled.
Parent round limits also bound retries when inputs change; collection refetches
the source, so changed content can produce a new fingerprint.

The same candidate/job ID is requeued. Waiting occupies admitted capacity but
releases the worker for other due work; automatic retries consume no new admission
quota. SQL failures retry persistence only, retaining returned responses in memory.
Acquisition receipts and completion/attempt tokens make lost acknowledgements
idempotent and reject stale writes. A permanently abandoned vote can be reclaimed
by a newly admitted cycle without allowing its old token to overwrite it.

Scheduled retries survive restart. Running work interrupted by restart becomes
`processing_interrupted` and requires an explicit retry. Committed votes remain
reusable; a response lost before commit cannot be recovered. Exactly-once
external invocation is not guaranteed. Run one API process/instance as required
by the [architecture](../technical-design-document.md) and
[deployment procedure](../DEPLOYMENT.md#collection-execution).

## Outcomes, diagnostics and explicit recovery

Use `execution_status` for queued/running/waiting/terminal work and
`polling_required` to decide whether to poll. The conclusion is separate:

| `outcome` | Meaning within the configured exploration scope |
| --- | --- |
| `null` | Work is active, queued or scheduled for retry. |
| `results` | Required checks concluded and datasets are available. |
| `empty` | Required checks concluded with no retained dataset. |
| `incomplete` | A required check did not conclude; usable saved results may exist. |

Successful fallback retains earlier failures without making the conclusion
incomplete. Admission caps describe a limited search scope, not exhaustive
discovery. Access barriers, failed branches and missing historical evidence are
not proof that no dataset exists. See [pipeline outcomes](pipeline-outcomes.md)
for aggregation and controlled diagnostic codes.

While waiting, progress exposes `execution_status=waiting_retry`, `outcome=null`
and `polling_required=true`. Diagnostics carry `recovery=automatic`, `retry_at`,
`attempt` and `max_attempts`. Running/immediately queued branches take priority
over waiting siblings in aggregate status; their retry diagnostics remain visible.

Owner-scoped diagnostics and retry commands return 404 for another owner's item.
Reading status never enqueues work. Failed candidates and failed, incomplete or
eligible empty collection jobs can be retried. Jobs whose diagnostics all declare
unsupported recovery are rejected. Explicit retries obey quotas, provider due
times and command idempotency; premature retries return 429 with `Retry-After`
without a receipt or quota charge. Replaying a key acknowledges the original
command, and acknowledging queued/running work does not accelerate its retry.
Saved results/associations remain available even if retry finds nothing new.

Job diagnostics expose method/resource history and coverage. Search diagnostics
export the current search snapshot and associated traces, with an export timestamp
and evidence gaps. Observations are guarded by the exact claim and retry cycle;
replayed observations update the same entry and cannot change a newer claim.
Final validated results retain their guarded atomic commit.

Diagnostics omit raw pages, provider exception bodies, cookies and secret URL
parameters. Method/model histories use bounded pages; follow `next_offset` and
inspect `history_truncated`/`checks_truncated` as defined by the
[API history contract](../api-integration.md#diagnostic-history). Historical jobs
may lack traces. Exports are observations, not complete historical replay.

## Optional browser

An empty `COLLECTION_BROWSER_URL` disables browser recovery. Enabling it requires
the private Compose `browser` profile, a shared random token of at least 32
characters and explicit host allowlists:

```dotenv
COLLECTION_BROWSER_URL=http://collection-browser:8002
COLLECTION_BROWSER_TOKEN=<random-secret-at-least-32-characters>
COLLECTION_BROWSER_HOSTS=dataverse.harvard.edu
COLLECTION_DATAVERSE_HOSTS=dataverse.harvard.edu
```

For the main proxy deployment, after setting these values in its private `.env`:

```sh
docker compose --profile browser config --quiet
docker compose --profile browser build
docker compose stop ai-commons-api
docker compose --profile browser up -d
```

The standalone API uses the same profile. Its equivalent commands are:

```sh
docker compose --env-file .env.api -f docker-compose.api.yml --profile browser config --quiet
docker compose --env-file .env.api -f docker-compose.api.yml --profile browser build
docker compose --env-file .env.api -f docker-compose.api.yml stop api
docker compose --env-file .env.api -f docker-compose.api.yml --profile browser up -d
```

Stopping the old API before replacement preserves single-instance ownership;
saved data volumes remain. For other operations, follow
[deployment](../DEPLOYMENT.md#collection-execution).

The browser endpoint is trusted configuration, never derived from page content;
it accepts HTTP/HTTPS without credentials, query or fragment. API host recognition
does not authorize browser navigation. Cookies stay in the isolated session.
JavaScript and normal navigation are supported; CAPTCHA solving, copied user
sessions, stealth identities and interactive login are unsupported. Persistent
barriers remain incomplete. Probes currently support same-origin resources;
cross-origin downloads, guestbooks and repository-specific flows need an adapter.

The service has no published port, application/database volume or model/database
secrets. Separate control/egress networks, a DNS-pinned HTTPS proxy and a container
firewall prevent private-destination access or direct proxy bypass.
`EGRESS_BLOCKED_CIDRS` applies to its firewall. The API has a narrow fixed-service
exception for port 8002; restart it if the browser address changes.

| Browser boundary | Limit |
| --- | --- |
| Concurrent sessions / slot wait | 1 / 30 seconds and remaining attempt budget |
| Navigation / resource probe | 30 seconds / 10 seconds, 64 KiB sample |
| Rendered HTML/metadata / control response | 1 MB / 2 MB |
| Proxy tunnel / concurrent tunnels | 16 MB, 300 seconds / 32 |
| Child-process lease / client close cleanup | At most 300 seconds / independent 3 seconds |
| Container memory / processes / temporary storage | 1 GiB / 256 / 256 MiB |

Lease expiry, failure or close kills the child process group. Chromium uses its
native sandbox as UID 10001 after dropping bootstrap capabilities. The seccomp
profile permits its unprivileged user namespace without granting
`CAP_SYS_CHROOT`. Authenticated control calls reject redirects and remain subject
to absolute request deadlines and the DNS caveat above.

## Configuration and validation

The [connector reference](collection-connectors.md) owns repository host/API
configuration. Shared record metadata transport settings are:

| Environment setting | Default | Accepted values |
| --- | --- | --- |
| `COLLECTION_RECORD_TIMEOUT_SECONDS` | `20` | Finite 1–120 seconds per request |
| `COLLECTION_RECORD_MAX_ATTEMPTS` | `3` | Integer 1–3, including the initial request |
| `COLLECTION_RECORD_MAX_WAIT_SECONDS` | `30` | Finite 0–60 seconds per retry pause |

These idempotent metadata reads retry transient network errors and HTTP
408/429/500/502/503/504 within the attempt budget. Invalid payloads, access
refusals and TLS/policy failures are not retried. A provider delay exceeding the
wait/budget limit is retained for manual recovery, never shortened. General
collector defaults are in [CollectorConfig](../../collector/config.py): 10-second
requests, five pages per source, 65,536-byte samples, three checks and one saved
distribution. Related connector metadata reads have separate bounded traversal
rules in the connector reference.

For changes, exercise [budget boundaries](../../tests/test_collection_budget.py),
[network deadlines](../../tests/test_collection_budget_network.py),
[durable budget claims](../../tests/test_collection_budget_persistence.py) and
[model recovery](../../tests/test_llm_recovery.py). Use simulated providers and a
disposable PostgreSQL database; ordinary verification needs no live model quota.
Browser security tests additionally cover service authentication/expiry and
private-address refusal. Follow [onboarding](../ONBOARDING.md) for test setup.
