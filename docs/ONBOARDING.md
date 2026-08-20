# Global Health Dataset Catalog — Onboarding

> Introduction document for new developers.  

> Goal: understand the project, how it works, and its key points without having to read the entire TDD.

---

## 1. The Project in 30 Seconds

**Global Health Dataset Catalog** is an application that searches for, identifies, and catalogs **official pages for global health datasets**.

The application does not download or store the datasets themselves.

It mainly stores:

- the dataset URL;

- its title;

- its publisher;

- how it was discovered;

- its probability score of being a dataset;

- its health relevance score;

- links to its files/APIs;

- the validation result for these links.

- its country or countries of origin, when this information is available;

### Simple Example

The system is given:

```text

https://data.example.org

```

The collector may discover:

```text

https://data.example.org/dataset/life-expectancy

```

It then analyzes this page and determines:

```text

Dataset probability: 0.92

Health probability: 0.85

```

If this link works, the dataset can be saved to the catalog.

---

# 2. General Architecture

The current architecture is intentionally simple.

```text

User

    ↓

Frontend React

    ↓

Backend FastAPI

    ↓

Collector Python

    ↓

External sources

    ↓

SQLite

```

The four main parts are:

### Frontend

```text

frontend/

```

React/Vite application.

It can be used to:

- view sources;

- filter results;

- monitor jobs;

- view collected datasets;

Debugging/administration functions:

- start a collection;

- test the collector.

---

### Backend

```text

backend/app/

```

FastAPI API.

Main responsibilities:

- expose HTTP endpoints;

- validate requests;

- start the collector;

- return results to the frontend.

---

### Collector

```text

collector/

```

This is the core of the discovery logic.

It handles:

```text

Discovery

    ↓

Extraction

    ↓

Classification

    ↓

Distribution detection

    ↓

Validation

```

---

### Database

```text

backend/global_health.db

```

SQLite is currently used to store metadata during development. The local database contains test data only and can be deleted and recreated if its schema becomes incompatible with the current code.

The long-term goal is to transition to **PostgreSQL** for a persistent or shared environment.

---

# 3. Repository Structure

The main structure is:

```text

project/

├── backend/

│   ├── app/

│   │   ├── main.py

│   │   ├── database.py

│   │   └── routes/

│   │       ├── sources.py

│   │       └── collector.py

│   ├── requirements.txt

│   └── global_health.db

│

├── collector/

│   ├── classification/

│   ├── discovery/

│   ├── extraction/

│   ├── storage/

│   ├── validation/

│   ├── config.py

│   ├── fetch.py

│   └── main.py

│

├── frontend/

│   ├── src/

│   │   ├── App.jsx

│   │   ├── main.jsx

│   │   └── styles.css

│   ├── package.json

│   └── vite.config.js

│

├── tests/

├── docs/

└── pyproject.toml

```

Key points:

```text

backend/   → API + DB

collector/ → collection logic

frontend/  → user interface

tests/     → expected system behavior

```


Key points:

```text

backend/   → API + DB

collector/ → collection logic

frontend/  → user interface

tests/     → expected system behavior

```

---

# 4. How the Collector Works

The collector prioritizes structured sources before using generic search:

```text
CKAN → Socrata → data.json / DCAT → Generic site
```

The idea is simple:

> use structured metadata when available and scrape HTML only when necessary.

More Open Data Platforms can be added 

---

# 5. Discovery

Discovery consists of finding URLs that may correspond to dataset pages. The collector first uses structured sources because they provide reliable metadata directly:

- **CKAN**: query the `status_show` and `package_search` APIs to retrieve available packages;
- **Socrata**: query the Socrata catalog to find datasets;
- **data.json / DCAT**: read the metadata and distributions published by the portal.

If none of these methods works, the collector uses a generic method: it checks `robots.txt`, locates sitemaps, and then selects candidate URLs whose HTML pages can be analyzed.

---

# 6. Page Classification

A discovered page is not automatically considered a dataset.

It receives two main scores.

## Dataset probability

Probability that the page actually represents **an individual dataset**.

Current threshold:

```text

dataset_probability >= 0.60

```

---

## Health probability

Probability that the content is health-related.

Minimum threshold:

```text

health_probability >= 0.35

```

Labels currently used:

```text

>= 0.75 → HEALTH

>= 0.35 → PARTIALLY_HEALTH

< 0.35 → NON_HEALTH

```

### Planned Evolution: LLM-Assisted Classification

This part will be further explored by **David** using an LLM, in addition to the current heuristics. The goal is to add a more precise semantic check when deterministic signals are not sufficient.

Examples of questions that the prompt could check:

- Does the content actually concern health?
- Does this page correspond to an individual dataset rather than a general catalog?
- Does the link provide access to the dataset, or to a page from which the dataset can actually be accessed?

> **Important:** the LLM component is a planned evolution. It does not yet describe the collector's current behavior.

---

# 7. Simple Classification Example

Page :

```text

Global Life Expectancy Dataset

```

Content:

```text

Life expectancy by country and year.

Download CSV.

World Health Organization.

```

The system might detect:

```text

title contains health-related terms

publisher = WHO

CSV link detected

dataset metadata detected

```

And produce:

```text

dataset_probability = 0.90

health_probability = 0.95

```

The page therefore passes the thresholds.



---

# 9. Important Signals

Signals are the clues used by the collector to evaluate a page. A single signal is not enough: several clues are combined to calculate the scores.

This part can be further developed with the LLM.

## Signals Indicating a Dataset

These are the strongest clues:

- the page contains `Schema.org Dataset` or `DCAT Dataset` metadata;
- it describes a title, publisher, or other dataset-specific information.

## Signals Indicating Data Access

These indicate that a file or API is probably available: `CSV`, `XLSX`, `JSON`, `API`, `export`, `download`, or `distribution`.

## Signals Indicating a Health Connection

The collector looks for these clues in the title, metadata, text, URL, and publisher. Examples include: `malaria`, `mortality`, `hospital`, `vaccination`, or `WHO`.

The more consistent signals a page contains, the more its probability of being a health dataset increases. Conversely, a page that only contains the word "data" without a file, metadata, or health-related content will receive a low score.

---

# 10. Distributions

A distribution is a way to access the data.

Examples:

```text

dataset.csv

dataset.xlsx

API endpoint

dataset.json

dataset.parquet

```

The collector supports, among others:

```text

CSV

TSV

XLS

XLSX

JSON

JSONL

XML

PARQUET

ZIP

GZ

SAV

DTA

SAS7BDAT

GEOJSON

API

```

The following formats are excluded by default:

```text

PDF

HTML

images

```

The goal is to identify **usable data**, not simply documents.

---

# 11. Distribution Validation

Finding a link is not enough.

The collector verifies that it works.

It first tries:

```text

HEAD

```

Then, if necessary:

```text

Partiel GET

```

The partial GET is used in particular when:

- HEAD is forbidden;

- the headers do not provide enough information;

- the server returns HTML;

- an additional check is needed.

The GET is limited to approximately:

```text

65 536 bytes

```

so that the entire dataset is not downloaded.

---

# 12. Saving Condition

A dataset is saved only if it has at least one validated distribution.

In summary:

```text

Dataset discovered 

      ↓

Dataset score >= 0.6 ?

      ↓

Health score >= 0.35 ?

      ↓

Distribution found ?

      ↓

Distribution validated ?

      ↓

SAVE

```

Without a valid distribution:

```text

not saved

```

---

# 13. Complete Pipeline

The pipeline can be summarized as follows:

```text

Source URL

    ↓

Portal type detection

    ↓

CKAN / Socrata / data.json / generic

    ↓

Discovery

    ↓

Candidate pages

    ↓

Extraction

    ↓

Dataset scoring

    ↓

Health scoring

    ↓

Distribution extraction

    ↓

HTTP validation

    ↓

Accepted dataset

    ↓

SQLite

```

---

# 14. Collection Jobs

A collection can be run as a job.

Typical cycle:

```text

pending

   ↓

running

   ↓

done

```

or:

```text

pending

   ↓

running

   ↓

error

```

The frontend regularly queries the backend to retrieve the job status.

---

# 15. Data Model

The main tables are:

## `data_sources`

Starting points configured manually to launch a collection. A source generally represents a portal or organization, along with its main URL.

Examples:

```text

WHO

CDC

HDX

```

These sources are the collector's entry points. They do not represent the datasets found: discovered datasets are stored separately in `collected_datasets`.

---

## `collected_datasets`

Main metadata for detected datasets.

It includes, among other fields:

```text

dataset_url

title

publisher

origin_countries

discovery_method

dataset_probability

health_probability

health_label

timestamps

```

---

## `collected_distributions`

Links to the data.

It includes, among other fields:

```text

url

format

probability

validation_ok

validation_http_status

```

---

## `dataset_discovery_observations`

History of dataset discoveries. This table records the date, source, and method used to find a dataset. The same dataset can therefore have several observations if it is discovered multiple times, for example through CKAN and then through a sitemap.

---

## `collection_jobs`

Collection status.

Example fields:

```text

source_url

status

saved_count

discovered_count

analyzed_count

error

timestamps

```

---

# 16. Important Endpoints

## Health

```text

GET /health

```

---

## Sources

```text

GET /sources

POST /sources

GET /sources/{id}/page

```

---

## Collector

```text

POST /collector/analyze-html

POST /collector/analyze-url

POST /collector/discover-url

POST /collector/collect-url

```

---

## Jobs

```text

POST /collector/collection-jobs

GET /collector/collection-jobs/{job_id}

```

---

## Results

```text

GET /collector/collected-datasets

```

---

# 17. Important Limits

The collector intentionally has several limits to prevent collections from taking too long.

Current values:

```text

HTTP timeout                 = 10 s

HTML analyze-url             = 1 MB maximum

sitemaps                     = 10 maximum

URLs sitemap                 = 1000 maximum

generic sitemap candidates   = 50

pages analyzed / source      = 5

distributions / dataset      = 1

```

These values reflect the current MVP behavior.

---

# 18. Important Network Security

The backend must not become a proxy for accessing the internal network.

Analyzed URLs must therefore use:

```text

HTTP

or

HTTPS

```

The following addresses are rejected:

```text

localhost

private IP

loopback

link-local

multicast

reserved IP

```

This notably reduces the risk of SSRF.

---

# 19. Local Database

SQLite is used for local development. The database included in the project contains only **test data** and is considered **disposable**.

If the schema becomes incompatible with the current code, the expected procedure is simply:

```text
delete backend/global_health.db
    ↓
restart the application
    ↓
the database is recreated with the current schema
```

There is therefore no need to write a historical migration to preserve the contents of this development database.

---

# 20. Storage Evolution

For the MVP and local development:

```text
SQLite
```

For a persistent, shared, or production environment, the goal is to move to:

```text
PostgreSQL
```

The PostgreSQL migration strategy will need to be defined when data actually needs to be preserved. This future migration is separate from the old SQLite test database, which can be recreated without preserving its contents.

---

# 21. Running the Project Locally

The current environment uses:

```text

Backend : FastAPI / Uvicorn

Port backend : 8001

Frontend : React / Vite

Port frontend : 5173

```

By default, the frontend points to:

```text

http://127.0.0.1:8001

```

For the backend:

```text

backend/requirements.txt

```

contains the main runtime dependencies.

The documented local launch uses Uvicorn from the backend directory, with the Python project available through `PYTHONPATH`.

For the frontend:

```text

VITE_API_BASE_URL=http://127.0.0.1:8001

```

is used to connect React to the backend.

For the exact commands and any changes, also check `README.md`.

---

# 22. Tests

The Python test suite currently contains:

```text

76 tests

```

In the last documented validation:

```text

76 passed

```

The Vite frontend build also passes.

The tests cover, among other areas:

```text

database

migrations

routes

collector pipeline

CKAN

Socrata

data.json

generic discovery

sitemaps

stored JSON

jobs

```

Before changing a collector rule, the tests are therefore a good source for understanding the expected behavior.

---

# 23. Main Technologies

```text

Python >= 3.9

FastAPI

Pydantic

Uvicorn

SQLite

React 18

Vite 5

pytest

ruff

```

---

# 24. What Is Not Yet Defined

The project is currently a local/internal MVP.

The following topics are not yet clearly defined:

```text

production hosting

authentication

roles / permissions

CI/CD

monitoring

alerting

backup strategy

rate limiting

retention policy

production database

```

The current architecture should therefore not be assumed to be the final production architecture.

---

# 25. Open Questions

The main remaining decisions concern:

1. define the target environment;

2. define which sources are considered official;

3. define authentication and roles;

4. determine the target volume;

5. define when and how to transition from SQLite to PostgreSQL;

6. decide whether FastAPI `BackgroundTasks` remain sufficient;

7. define CI/CD, monitoring, and backups;

8. define the criteria used to measure collector quality;

9. clarify the role of the LLM in classification and the criteria for calling the model.

---

# 26. Recommended Code Reading Order

For someone joining the project, the easiest approach is to read the code in this order:

```text

1. README.md

       ↓

2. collector/main.py

       ↓

3. collector/discovery/

       ↓

4. collector/classification/

       ↓

5. collector/extraction/

       ↓

6. collector/validation/

       ↓

7. backend/app/routes/collector.py

       ↓

8. backend/app/database.py

       ↓

9. tests/

       ↓

10. frontend/src/App.jsx

```

The goal is to understand first:

```text

how a dataset is found

```

before looking at:

```text

how it is displayed in the interface

```

---

# 27. Mental Model to Remember

If you remember only one thing:

```text

The system is given a source

        ↓

It searches for dataset pages

        ↓

It checks whether they really look like datasets

        ↓

It checks whether they are health-related

        ↓

It looks for associated files/APIs

        ↓

It checks that these links work

        ↓

It saves only accepted results

```

---

# 28. Summary

The project has three main responsibilities:

### 1. Discover

```text

Where are the datasets?

```

### 2. Qualify

```text

Is it really a dataset?

Is it health-related?

```

### 3. Validate

```text

Is there actually a usable file or API?

```

The current system is functional and tested as a local MVP. The development SQLite database is disposable and can be recreated when its schema changes. The next major developments include improving classification with an LLM and, eventually, transitioning to PostgreSQL for a persistent or shared environment.
