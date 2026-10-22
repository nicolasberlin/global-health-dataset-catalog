# Research reports and investigation tools

This directory holds reports generated while using the API. Start with the
[README quick start](../README.md#quick-start) to run your first search.

```text
research/
├── api/
│   ├── outputs/       JSON reports from scripts/api_client.py
│   └── sessions/      Private public-session cookies, recovery state and client lock
└── search-diagnostics.md   Guide to interpreting reports and diagnostic evidence
```

Generated reports and session files are private and excluded from Git. They
appear when you run searches with the client. Accepted dataset records also remain in
PostgreSQL; neither the reports nor the database contain complete dataset files.

## Read a client report

The default file is `api/outputs/search-report.json`, relative to this directory.
The client updates it during the run and replaces it on the next run. Copy the
report manually if you want to keep it for an investigation.

| JSON field | Meaning |
| --- | --- |
| `query`, `search_id` | Search text and the ID used to retrieve that search |
| `progress` | Current server state, available results, warnings and errors |
| `datasets` | Retrieved dataset records: metadata and links |
| `diagnostics` | Classification and collection observations explaining the result |
| `error` | A client or HTTP failure, when present |

A completed search with no accepted datasets differs from a failed step. Read
`progress` and `diagnostics` before drawing a conclusion. Fields can be absent
if retrieval stops early. Retrieve the most recent search with `--latest`,
which never restarts failed work. After acceptance, submitting another query
creates a new operation.
See the [API integration guide](../docs/api-integration.md) for client options.

## Session files

`api/sessions/api.cookies` is created only with `API_CLIENT_MODE=public`. It preserves the
visitor identity needed to retrieve that visitor's searches. The normal local
quick start uses loopback access as `local-user` and does not create this cookie.
Session cookies are private access credentials. RCP keys belong in `.env.api`,
not in reports or investigation notes.

`api/sessions/pending-search.json` stores the key, query and context of a request
whose acceptance is not yet confirmed. After an uncertain submission, rerun the
same `--query` with the same server and session; the key is reused automatically.
`--latest` does not erase this file. An acknowledged or rejected request clears
it. Do not remove it to bypass recovery, as doing so could create duplicate work.
The adjacent process lock prevents concurrent clients from overwriting these files.

## Investigate a result

The [search diagnostics guide](search-diagnostics.md) explains how to interpret
the generated report and inspect the available API evidence. No manual forms
are required to run or investigate a search.

The [Search Lab](../search_lab/README.md) is a separate optional tool. Its code,
guides and private observations live together in `search_lab/`; it does not
write to `research/api/`. See the
[laboratory data guide](../search_lab/data/README.md) before moving or removing observations.
