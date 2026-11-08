# Search workflow end-to-end tests

These tests submit `malaria` through HTTP and exercise the real FastAPI lifespan,
Uvicorn, SearchWorker, ClassificationWorker, CollectionWorker and PostgreSQL writes.
Only external provider and LLM HTTP responses are simulated. Unexpected requests,
missing requests and duplicate requests fail the test.

## Run

Use Python 3.11 or newer with the project's development dependencies installed
(`python -m pip install -e '.[dev]'`) and a running Docker daemon. Docker must be
able to use the `postgres:16` image; its first use may download it.

From the repository root:

```sh
python -m pytest --confcutdir=tests/e2e tests/e2e/test_search_workflow.py -v
```

Use `-k minority_vote` to select one scenario, or `-s` to show the result and
external request journal. `--confcutdir` excludes the repository's other
application fixtures while retaining the fixtures in this directory.

Each scenario starts a disposable PostgreSQL container and a local Uvicorn
process on dynamically assigned loopback ports, then stops both during teardown.
The tests run the backend from this checkout; installed-package independence is
covered separately by the packaging tests.

## Scenarios

| Scenario | Expected result |
| --- | --- |
| `success` | One relevant, eligible dataset with an accessible CSV is saved. |
| `not_relevant` | The candidate is rejected; no collection job or dataset is saved. |
| `minority_vote` | One positive vote out of three is rejected; no dataset is saved. |
| `not_eligible` | The relevant candidate's page is rejected; no dataset is saved. |
| `csv_404` | CSV validation fails; the search outcome is `incomplete`, with no dataset saved. |
| `multiple_candidates` | Three candidates are discovered; the two relevant datasets are saved. |

Assertions check the progress, catalogue-by-ID and diagnostics HTTP responses,
individual votes, resource validation, database persistence and the exact external
request journal. Database observation uses a read-only connection.

## Files

- `test_search_workflow.py`: the POST, wait and GET workflow and final results.
- `scenarios.py`: controlled inputs and expected outputs.
- `conftest.py`: fixtures for services, client and checks.
- `support/server.py`: external HTTP response control and network guard.
- `support/runner.py`: Uvicorn startup and shutdown.
- `support/client.py`: polling, detailed assertions and external request journal.
- `../helpers/postgres.py`: shared disposable PostgreSQL lifecycle.
- `../helpers/paths.py`: shared repository paths.
