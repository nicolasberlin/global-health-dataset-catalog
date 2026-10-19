# Global Health Dataset Catalog

A FastAPI and PostgreSQL API for finding, classifying and cataloguing
global health datasets.

It searches the local catalogue first, uses external repositories when needed,
and runs background classification and collection. It stores **metadata and
links**, with bounded access checks rather than complete dataset downloads.

## Quick start

To run the project locally, you need:

- **Python 3.11 or later** — [installation](https://www.python.org/downloads/).
- **Docker with Docker Compose 2.3.0 or later** — [Docker installation](https://docs.docker.com/get-started/get-docker/) · [Compose installation](https://docs.docker.com/compose/install/).
- **EPFL laboratory access and API keys** for the three configured RCP models.
- An internet connection.

Docker installs PostgreSQL and the application dependencies automatically.

Check your installation before continuing:

```sh
python3 --version
docker compose version
docker info
```

If you have not downloaded the project yet, [install Git](https://git-scm.com/install/)
and clone it:

```sh
git clone https://github.com/nicolasberlin/global-health-dataset-catalog.git
cd global-health-dataset-catalog
```

You can also download and extract the repository's ZIP from GitHub without Git.
Run the following commands from the repository root.

### 1. Prepare your configuration

```sh
python3 scripts/setup_api.py
```

The helper creates two private, Git-ignored files:

| File | What you need to do |
| --- | --- |
| `.env.api` | Fill in the three RCP keys below; other settings are generated |
| `.env.api-client` | Nothing: the local address and matching API token are generated |

### 2. Add your model credentials

Open `.env.api` and replace these values with your own keys:

```dotenv
RCP_DEEPSEEK_API_KEY=your-deepseek-key
RCP_GEMMA_MEDITRON_API_KEY=your-gemma-key
RCP_APERTUS_MEDITRON_API_KEY=your-apertus-key
```

The database password and API access token are already configured. Rerunning the
helper preserves existing files and reports conflicts without replacing secrets.
The `.env.local` and laboratory settings are for other workflows and are not
loaded by these commands.

### 3. Start the API and run a search

```sh
docker compose --env-file .env.api -f docker-compose.api.yml up -d --build
python3 scripts/test_api.py --query "pneumonia"
```

The first build can take a few minutes. The client waits up to 60 seconds for
initial API readiness, submits a search, follows its progress, then fetches the
saved datasets and diagnostics. Real searches consume provider/model quotas.

- API: `http://127.0.0.1:8001`
- Interactive API documentation: `http://127.0.0.1:8001/docs`
- Report: `research/api/outputs/api-test.json`

The report is updated during the run, and a new search replaces the default
report. To keep separate reports, pass
`--output research/api/outputs/pneumonia.json`. Accepted dataset records also
remain in PostgreSQL. See [reading reports](research/README.md) for the fields
and the difference between an empty result and a failed step.

## Choose a Docker configuration

Always specify the Compose file for your workflow:

| File | Purpose |
| --- | --- |
| [`docker-compose.api.yml`](docker-compose.api.yml) | API and PostgreSQL; use this for the quick start above |
| [`docker-compose.local.yml`](docker-compose.local.yml) | PostgreSQL only; run Python manually using [onboarding](docs/ONBOARDING.md#start-locally) |
| [`docker-compose.yml`](docker-compose.yml) | Internal EPFL deployment behind existing Traefik infrastructure; requires the [deployment configuration](docs/DEPLOYMENT.md) |

## Stop and resume

```sh
docker compose --env-file .env.api -f docker-compose.api.yml down
```

This keeps the database volume. Adding `--volumes` deletes that volume and its
saved data. To resume later, run the same startup command from step 3 and follow
your latest search without submitting another:

```sh
python3 scripts/test_api.py --latest
```

This resumes tracking only. Tasks interrupted during shutdown can require an
explicit [retry](docs/api-integration.md#explicit-retries); saved results remain.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Docker is unavailable | Start Docker, then retry the startup command |
| Compose rejects the top-level `name` field or is older than 2.3.0 | Install the current Compose plugin and use `docker compose`; see the [Linux installation guide](https://docs.docker.com/compose/install/linux/) |
| Connection refused or readiness fails | Inspect the service status and logs below; check the database and all three model settings |
| Model calls fail | Verify each RCP key has access to its configured model; readiness checks configuration, not provider availability |
| Schema validation fails after updating | This release uses one initial schema for a fresh database; earlier pre-release volumes are not upgraded automatically. Follow [schema operations](docs/DEPLOYMENT.md#schema-validation-and-retired-source-administration) |
| HTTP 401 | Check that the tokens in `.env.api` and `.env.api-client` match; rerun the setup helper to detect conflicts |
| Old client settings take precedence | Previously exported `API_TOKEN` and `API_BASE_URL` override `.env.api-client`; unset them before retrying |
| Port 8001 is occupied | For a new setup, use `python3 scripts/setup_api.py --port 8002`; for existing files, align `API_PORT` and the client `API_BASE_URL` |

```sh
docker compose --env-file .env.api -f docker-compose.api.yml ps
docker compose --env-file .env.api -f docker-compose.api.yml logs --tail=100 api
```

For an existing configuration with several token owners, run the setup helper
with `--owner OWNER`. Keep the existing database password when reusing its volume.
The [API guide](docs/api-integration.md) covers client options, authentication,
retry rules and connecting to an API deployed elsewhere.

## Next steps

You only need the quick start above to try the API. Choose another guide when
you need to integrate, change or deploy it:

| Guide | Use it to |
| --- | --- |
| [API integration](docs/api-integration.md) | Build your own client: commands, progress, authentication, results and retries |
| [Developer onboarding](docs/ONBOARDING.md) | Run Python outside Docker, change code and run tests |
| [Architecture](docs/technical-design-document.md) | Understand modules, persistence, collection and safety constraints |
| [Deployment](docs/DEPLOYMENT.md) | Configure a server, proxy, database operations and maintenance |

The optional [Search Lab](search_lab/README.md) has its own interface and private
observations; it is independent of the API quick start. [Research files](research/README.md)
explain generated reports and how to interpret diagnostic evidence.

## Project layout

```text
backend/app/       FastAPI routes, PostgreSQL access and background workers
collector/         Repository discovery, classification and bounded validation
browser/           Isolated browser service for collection fallback
deploy/            Example Traefik proxy configuration
scripts/           Local API configuration helper and HTTP client
tests/             Python unit and integration tests
docs/              Integration, development, architecture and deployment guides
research/          Private generated API reports and diagnostic-reading guide
search_lab/        Optional laboratory with its own small interface and local data
```

## Current limits

- Run one API process and one instance per application database schema.
- Model decisions and sampled resource checks do not guarantee scientific
  quality, publisher authority, licensing compliance or complete data access.
- This is an actively developed project. Automated tests simulate external
  providers; they do not certify live provider availability or production capacity.

The [validation guide](docs/ONBOARDING.md#validation) explains local checks and
the [GitHub workflow](.github/workflows/ci.yml) defines automated checks.

## License

[Apache License 2.0](LICENSE).
