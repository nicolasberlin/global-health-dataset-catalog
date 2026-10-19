# Research reports and investigation tools

This directory holds reports generated while testing the API. Start with the
[README quick start](../README.md#quick-start) to run your first search.

```text
research/
├── api/
│   ├── outputs/       JSON reports from scripts/test_api.py
│   └── sessions/      Private client cookies in public-session mode
├── search-diagnostics.md   Optional manual investigation guide
└── templates/             Blank trace and report templates
```

Generated reports and session files are private and excluded from Git. They
appear when you run your own tests. Accepted dataset records also remain in
PostgreSQL; neither the reports nor the database contain complete dataset files.

## Read a client report

The default file is `api/outputs/api-test.json`, relative to this directory.
The client updates it during the run and replaces it on the next run. Use the
client's `--output` option to keep a separate file for each investigation.

| JSON field | Meaning |
| --- | --- |
| `query`, `search_id` | Search text and the ID used to retrieve that search |
| `progress` | Current server state, available results, warnings and errors |
| `datasets` | Retrieved dataset records: metadata and links |
| `diagnostics` | Classification and collection observations explaining the result |
| `error` | A client or HTTP failure, when present |

A completed search with no accepted datasets differs from a failed step. Read
`progress` and `diagnostics` before drawing a conclusion. Fields can be absent
if tracking stops early or `--no-wait` is used. Resume the existing search with
`--latest` or `--search-id`; submitting another query creates a new operation.
See the [API integration guide](../docs/api-integration.md) for client options.

## Session files

`api/sessions/api.cookies` is created only with `--auth public`. It preserves the
visitor identity needed to retrieve that visitor's searches. The normal local
quick start uses the token from `.env.api-client` and does not create this cookie.
Session cookies are private access credentials. RCP keys belong in `.env.api`,
not in reports or investigation notes.

## Investigate a result

The optional [search diagnostics guide](search-diagnostics.md) and its blank
[report](templates/search-report.md) and [trace](templates/search-trace.json)
templates help maintainers record evidence and compare attempts. They are
independent of the client-generated JSON report and do not need to be completed
to use the API.

The [Search Lab](../search_lab/README.md) is a separate optional tool. Its code,
guides and private observations live together in `search_lab/`; it does not
write to `research/api/`. See the
[laboratory data guide](../search_lab/data/README.md) before moving or removing observations.
