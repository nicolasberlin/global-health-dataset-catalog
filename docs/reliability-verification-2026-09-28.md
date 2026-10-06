# Reliability integration verification — 2026-09-28

## Revisions and release status

- Integration branch: `codex/reliability-verification`.
- Reviewed baseline: `60e45efc1c546db01baaeb4d98d7fdde29c3f1be`.
  This already contains the reliability implementation and the polling merge
  `e7282c7` (PR #9, implementation `d76afbf`). No merge conflict remains.
- Locally verified code revision: `fd3d74e5c59172ef9a306dbcfb404feccd019f29`.
  The subsequent documentation commit records this verification without changing
  executable code or tests.
- Baseline CI: [run 36232736717](https://github.com/nicolasberlin/global-health-dataset-catalog/actions/runs/36232736717)
  completed successfully for the exact baseline SHA. All six jobs passed:
  Python 3.9/PostgreSQL, Python 3.11/PostgreSQL, frontend, three-browser sessions,
  backend image/firewall, and Traefik rate limits.
- Corrected-revision CI: **pending publication approval**. Automatic approval
  review rejected pushing the new branch to the existing GitHub remote because
  publication authorization and destination trust were not established. No push,
  pull request, merge, or deployment was performed. Baseline CI success does not
  certify the new revision. TODO 1's CI/release gate remains open.

## Review and targeted correction

The existing prefix parser, bounded sampling, transaction boundaries, retry
backoff, and claim-version guards were retained. Model and collection execution
remain outside persistence-only retries. Success/error finalization is guarded by
the claimed `updated_at`; polling only reads state, and vote progress updates do
not change that claim version. Classification and its follow-up reservation commit
together; collection datasets and terminal job status commit together.

The review reproduced one JSON validation defect: Python's JSON decoder accepted
`NaN`, `Infinity`, and `-Infinity` as numeric constants, allowing malformed complete
and partial responses to be marked available. Both decoding paths now reject
those constants. Six regression cases failed before the change and pass afterward.

Four added PostgreSQL cases synchronize two recovering persistence calls for the
same claim, covering collection/classification and success/error outcomes. Exactly
one finalization succeeds, with no duplicate datasets, observations, jobs, or
associations. Two further cases publish actual vote progress and read the grouped
search snapshot before worker completion, verifying that the claim remains valid
and that polling observes the resulting collection state.

Existing tests cover partial/invalid JSON, every byte boundary of a UTF-8 document,
range validation, lost commit acknowledgements, stale attempts after explicit
retry, retryable database errors, worker-slot retention, and one execution of
model/collection work across terminal persistence retries. Disconnects in the
persistence tests are injected around real PostgreSQL operations; this is not a
production outage or host-restart test.

## Local validation

Environment: Python 3.9.6, PostgreSQL 16 in a disposable container bound to
loopback, Node.js 22.19.0. No production database or model credentials were used.

| Check | Result |
| --- | --- |
| Ruff, `ruff check .` | Passed |
| Full Python suite with PostgreSQL, current backend image and Traefik | 580 passed, 3 skipped |
| Frontend, `npm test` | 59 passed |
| Production frontend build, `npm run build` | Passed |
| Playwright, `npm run test:browser` | 15 passed across Chromium, Firefox and WebKit |
| Git whitespace check | Passed |

The three skipped tests are explicitly optional Traefik throughput benchmarks;
the five required proxy correctness cases and the container egress test passed.
The backend image was rebuilt after the JSON correction. Frontend/browser checks
ran on the baseline; the corrected revision leaves their source and harnesses
unchanged. Browser coverage includes grouped polling of ten candidates through
collection and stopping after completion.

The full Python invocation used the disposable test connection through
`TEST_DATABASE_URL`, `EGRESS_TEST_IMAGE=global-health-reliability:20260928`, and
`TRAEFIK_TEST_IMAGE=traefik:v3.7.5`, then `.venv/bin/pytest -ra`. Test credentials,
environment files, raw logs, and generated browser/build output are not committed.
The reviewed code commit contains only the two JSON validation files and two test
files; `.env`, `.env.*`, and `key.txt` are not tracked.

## Remaining gate and operational limit

After approval, push this integration branch, inspect CI for its exact head SHA,
and record the successful run before selecting the final release revision. Do not
infer deployment from local validation or baseline CI.

Recovery still requires one API process and one instance. Completed outcomes are
retained in memory during database outages; forced process termination can lose
unpersisted outcomes, and startup marks interrupted work as failed. This review
does not introduce durable result spooling, worker leases, or new retry policies.
