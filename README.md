# Global Health Dataset Catalog

A FastAPI and PostgreSQL API for finding, classifying and cataloguing
global health datasets.

It searches the local catalogue first, uses external repositories when needed,
and runs background classification and collection. It stores **metadata and
links**, with bounded access checks rather than complete dataset downloads.

## Quick start

Run the Python API on your machine and PostgreSQL in Docker. No API access token,
account, frontend or Node.js installation is required.

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Docker with Compose 2.3.0+, and credentials for all three configured EPFL RCP
models. Model-provider credentials are separate from access to this API.

```sh
git clone https://github.com/nicolasberlin/global-health-dataset-catalog.git
cd global-health-dataset-catalog
uv sync --locked --python 3.11
uv run --locked python scripts/setup_api.py
```

Fill in `RCP_DEEPSEEK_API_KEY`, `RCP_GEMMA_MEDITRON_API_KEY` and
`RCP_APERTUS_MEDITRON_API_KEY` in the generated, Git-ignored `.env.api`.
The helper generates a PostgreSQL password and a local client configuration.
Rerunning it preserves existing files and secrets.

Start PostgreSQL and the API:

```sh
uv run --locked python scripts/start_api.py
```

The launcher uses `docker-compose.local.yml`, waits for PostgreSQL and runs one
API process on `127.0.0.1:8001` with proxy headers disabled. Keep this terminal open.
In another terminal:

```sh
uv run --locked python scripts/api_client.py --query "pneumonia"
```

The client submits one keyed search, tracks it and fetches saved datasets and
diagnostics. Real searches consume model/provider quotas.

- API: `http://127.0.0.1:8001`
- Interactive documentation: `http://127.0.0.1:8001/docs`
- Report: `research/api/outputs/search-report.json`

All local searches belong to `local-user`. If submission acceptance is unknown
after a connection failure, repeat the same `--query`: the client reuses its
saved idempotency key automatically. After acceptance, retrieve the most recent
search without submitting another query:

```sh
uv run --locked python scripts/api_client.py --latest
```

Only `--query`, `--latest` and optional `--timeout SECONDS` are exposed. The client
waits up to 15 minutes by default, checks progress every 3 seconds and uses a
30-second deadline per HTTP request. Stopping retrieval does not cancel accepted
work. Latest always refers to the most recent search and does not restart failures.
The default setup uses port `8001` without writing `API_PORT` or `API_BASE_URL`
into the local configuration files. These overrides are only needed for a
custom address. Connection settings live in `.env.api-client`: `API_BASE_URL`, `API_CLIENT_MODE`
(default `local`) and, for public sessions, `API_PUBLIC_ORIGIN`. The file and
session/report paths are loaded automatically. See the
[client guide](docs/api-integration.md#python-client-without-the-interface).


## Access and deployment

| Configuration | Purpose |
| --- | --- |
| `local` (default) | Personal instance on loopback; no credentials sent to the API |
| `public` | Anonymous visitors identified by signed cookies, with IP and workload limits |

Public visitors use anonymous sessions and do not need accounts.
Use [anonymous sessions](docs/reference/anonymous-visitor-sessions.md) and review
[deployment](docs/DEPLOYMENT.md) before exposing an instance.

| Compose file | Purpose |
| --- | --- |
| `docker-compose.local.yml` | Local PostgreSQL, used by `scripts/start_api.py` |
| `docker-compose.api.yml` | Public-session API and PostgreSQL; requires public-session configuration |
| `docker-compose.yml` | Public-session API behind the existing internal Traefik deployment |

The public container templates are not the local quick start. Container traffic
may reach the API through a bridge address rather than loopback; do not weaken
local address checks to accommodate it. Internet deployment requires HTTPS,
a stable signing secret, trusted proxy configuration and traffic limits.
`.env.public.example` lists public configuration and quota settings.

## Stop, resume and troubleshoot

Ctrl+C stops the Python API. PostgreSQL remains running. To stop it without
removing data:

```sh
docker compose --env-file .env.api -f docker-compose.local.yml stop postgres
```

Run `scripts/start_api.py` again to resume. Do not remove database volumes unless
you explicitly intend to delete their contents.

| Problem | Action |
| --- | --- |
| Docker unavailable | Start Docker; inspect `docker compose --env-file .env.api -f docker-compose.local.yml logs postgres` |
| Port occupied | For a new setup, use `scripts/setup_api.py --port 8002`; preserve the existing PostgreSQL port and volume |
| Model/readiness failure | Check all three provider keys; readiness validates configuration, not provider availability |
| Existing database authentication failure | Preserve the password used to initialize its volume; generating another password does not change PostgreSQL |

The native local process keeps the application destination checks, but does not
use the container's kernel egress firewall. The public container runtime retains
that firewall and privilege drop.

## Next steps

You only need the quick start above to try the API. Choose another guide when
you need to integrate, change or deploy it:

| Guide | Use it to |
| --- | --- |
| [API integration](docs/api-integration.md) | Build your own client: commands, progress, authentication, results and retries |
| [Developer onboarding](docs/ONBOARDING.md) | Run Python outside Docker, change code and run tests |
| [Architecture](docs/technical-design-document.md) | Understand modules, persistence, collection and safety constraints |
| [Python function index](docs/reference/python-function-index.md) | Find function and method signatures, with links to their source code |
| [Deployment](docs/DEPLOYMENT.md) | Configure a server, proxy, database operations and maintenance |

The optional [Search Lab](search_lab/README.md) has its own interface and private
observations; it is independent of the API quick start. [Research files](research/README.md)
explain generated reports and how to interpret diagnostic evidence.

## Separately maintained web interface

The main frontend and its additional API routes, storage helpers and tests live
locally in `interface_web/`. That whole directory is excluded from Git and the
backend image; it is not part of this public repository. The core API and Python
client do not depend on it. Search Lab remains versioned in `search_lab/`.

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
