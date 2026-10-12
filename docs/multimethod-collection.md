# Multi-method record collection

This implementation applies to accepted repository candidates. The existing
React/Vite interface, FastAPI service, PostgreSQL queues and model checkpoints
remain in place. The source/catalog crawler retains its existing behavior.

## Execution

`collect_repository_candidate_with_report` delegates to
`collector.collection.orchestrator.collect_record`:

1. A recognized Dataverse or Zenodo URL is resolved through its official record
   API using the configured connector registry.
2. If this does not produce a validated resource, fetch the record's HTML and
   inspect the existing links/structured metadata.
3. If configured for that host, render the same record in a disposable Chromium
   session. Dataverse metadata may be requested inside that session. Resource
   probes use the same session, without exporting its cookies.

Every method uses the existing dataset classifier and resource validator. A
download link alone is insufficient. A valid semantic rejection stops the run;
the browser is not used to seek a different model vote. A file record resolves
that file, never every file from its parent dataset. Connectors produce a
`NormalizedRecord`, converted to the existing contracts without changing
acceptance criteria. See [Collection connectors](collection-connectors.md)
for supported URL scope, configuration and schema migration 13 to 14.

The shared policy checks at most three resources and saves at most one validated
distribution. The same failed HTTP resource can be checked once again in a
browser session, within that shared limit. Coverage records discovered, checked
and validated resources, the discovery method and whether the limit was reached.
The listing describes the supported record scope, not the whole repository.
Files and formats excluded by the existing data-resource rules are not counted
as eligible links. Exhaustive coverage is not guaranteed.
Version-pinned Dataverse dataset URLs use their HTML/browser page rather than
silently resolving the API's default latest version.

`results` means validated metadata/resource evidence was saved atomically.
`empty` means no supported downloadable resource was found without an unresolved
failure. Access barriers, failed resource checks and expired budgets yield
`incomplete`. An earlier failed method remains in history but does not make a
later successful collection incomplete. The catalog stores metadata and links;
it does not download entire files. Sample evidence can identify ZIP without
proving that the whole archive is an intact Excel workbook.

## Persistence and diagnostics

Schema migration 11 → 12 adds `collection_method_attempts`,
`collection_resource_checks` and summary/coverage fields on `collection_jobs`.
It preserves existing jobs, votes and datasets. Observations are guarded by the
job's exact claim timestamp and retry cycle. Writing history does not change
that timestamp. Replayed observations update the same method/check; old workers
cannot write into a newer claim. Final validated results retain their existing
guarded atomic commit.

- `GET /collector/collection-jobs/{id}/diagnostics` returns method/check history
  and coverage for a job accessible to the current owner.
- `GET /collector/searches/{id}/diagnostics` exports the current search snapshot
  and associated collection traces, with an export timestamp and evidence gaps.
- The interface exposes **Collection details** and **Export diagnostic trace**.
- **Retry collection** supports failed, incomplete and empty terminal jobs. It
  creates a new collection cycle with existing model checkpoints and an
  idempotent command; it does not run merely when reading a status.

Diagnostics omit raw pages, provider exception text, cookies and secret URL
parameters. Only the latest 1,000 method observations per job are returned; a
truncation flag is explicit. Historical jobs predating this migration have no
method history. Exported snapshots are partial evidence, not a reconstruction of
every historical search event. Use the [diagnostic guide](diagnostic-recherche.md)
to write a report and identify missing evidence.

## Optional browser deployment

The browser service is disabled when `COLLECTION_BROWSER_URL` is empty. Enable
it with the `browser` Compose profile and the same private random token (minimum
32 characters) in the API and service. Configure these values in the untracked
deployment environment:

```dotenv
COLLECTION_BROWSER_URL=http://collection-browser:8002
COLLECTION_BROWSER_TOKEN=<random-secret-at-least-32-characters>
COLLECTION_BROWSER_HOSTS=dataverse.harvard.edu
COLLECTION_DATAVERSE_HOSTS=dataverse.harvard.edu
```

Validate the configuration and build the images before rolling out:

```sh
docker compose --profile browser config --quiet
docker compose --profile browser build
```

Follow the [single-instance deployment procedure](DEPLOYMENT.md#collection-execution)
when starting the replacement API with the browser profile. The browser has no
published port, no application/database volume and no model/database secrets.
The API receives a narrow exception for the fixed service on port 8002. The
service has separate control and egress networks and a DNS-pinned HTTPS proxy
that refuses private destinations, including private DNS answers. A container
firewall also prevents direct private traffic bypassing that proxy. Deployment
`EGRESS_BLOCKED_CIDRS` applies to the browser firewall as well.
Restart the API when the browser service's address changes so its fixed egress
exception is rebuilt.

There is one browser slot. Waiting for it is bounded by 30 seconds and the
remaining collection budget. Each navigation is capped at 30 seconds, each
resource probe at 10 seconds/64 KiB, rendered HTML/metadata at 1 MB, control
responses at 2 MB and proxy tunnels at 16 MB/180 seconds. The proxy accepts at
most 32 concurrent tunnels. The service lease never exceeds 180 seconds and
kills the whole child process group on expiry/failure/close. Memory is capped at
1 GiB, processes at 256 and temporary storage at 256 MiB. Existing HTTP/model
operations retain their cooperative deadline limitations documented in
[collection-budget.md](collection-budget.md).

Production runs Chromium's native sandbox as UID 10001, with all bootstrap
capabilities dropped. The seccomp profile is derived from the
[Playwright scraping profile](https://playwright.dev/docs/docker#crawling-and-scraping),
with `chroot` also permitted for Chromium's unprivileged user namespace; it does
not grant `CAP_SYS_CHROOT` to the service. JavaScript, normal navigation and
ordinary session cookies are supported. CAPTCHA solving, copied user sessions
and stealth identities are not implemented. Persistent challenges or access
permissions remain explicit incomplete outcomes.

The current browser probe supports same-origin resources. Downloads hosted on
a different origin, interactive login, guestbook forms and repository-specific
flows may require another adapter. Changing the allowed hosts is an explicit
deployment configuration change, not something derived from page content.

## Verification

Fixtures cover API → HTML and barrier → browser recovery, shared resource
limits, negative model decisions, file scope, diagnostics and expired budgets.
PostgreSQL tests exercise owner isolation, additive migration, replayed writes,
stale claims and explicit retries. Interface tests cover lazy authenticated
history reads, cancellation and empty-job retries. Security tests exercise the
real proxy's private-address refusal and browser service authentication/expiry.

On 2026-10-09, local Harvard job 36 was explicitly retried. Its official API
responded successfully on that attempt; all three page votes succeeded, a range
probe of file 6811860 returned HTTP 206 with ZIP evidence, and one dataset was
saved with outcome `results`. This does not imply that all Harvard requests
always succeed or that JavaScript was needed for that particular retry.
Separately, the isolated container rendered the real Harvard page and its
metadata with HTTP 200, then read a capped HTTP 206 sample of the same file using
the browser session. These are current reproductions, not evidence about the
original failed search.

Official adapter reference: [Dataverse native API](https://guides.dataverse.org/en/latest/api/native-api.html).
