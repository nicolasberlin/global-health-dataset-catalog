# Collector Pipeline Diagram

> Current runtime flow, last verified 2026-09-04.

The application has two separate flows. Repository search classifies candidates
for display. Source collection decides whether discovered records can be stored.

## 1. Complete HTTP Flow

```mermaid
flowchart LR
    UI["React frontend"]
    Sources["/sources"]
    RepoSearch["/collector/search-datasets"]
    RepoClassify["/collector/classify-repository-result"]
    Jobs["/collector/collection-jobs"]
    JobStatus["/collector/collection-jobs/{id}"]
    Results["/collector/collected-datasets"]
    DB[(PostgreSQL)]

    UI --> Sources --> DB
    UI --> RepoSearch --> DB
    UI --> RepoClassify
    UI --> Jobs --> DB
    UI --> JobStatus --> DB
    UI --> Results --> DB
```

There is no current manual pasted-HTML/URL test route. Repository search and
source collection are separate API workflows.

## 2. Repository Search Pipeline

```mermaid
flowchart TD
    Query["User query"] --> Route["POST /collector/search-datasets"]
    Route --> LocalQuery["Remove data/dataset/database<br/>for PostgreSQL only"]
    LocalQuery --> DBSearch["english full-text search"]
    DBSearch --> Match{"Full-text match?"}
    Match -->|yes| Local["origin=database<br/>datasets + distributions"]
    Local --> LocalUI["Display 'Déjà dans la base'<br/>no IA controls"]
    Match -->|no| Service["search_repository_metadata(original query)"]
    Service --> DataCite["DataCiteRepositorySearchProvider"]
    DataCite --> API["DataCite /dois<br/>resource-type-id=dataset"]
    API --> Normalize["Normalize RepositorySearchResult"]
    Normalize --> Filter{"Title and HTTP(S) URL present?"}
    Filter -->|no| MetadataWarning["Drop result + warning"]
    Filter -->|yes| Candidates["Return origin=online candidates"]
    Candidates --> Workers["Progressive frontend workers"]
    Workers --> ClassifyRoute["POST /collector/classify-repository-result"]
    ClassifyRoute --> RepoClassifier["Repository relevance classifier<br/>1-voter audit wrapper"]
    RepoClassifier --> Model["1 EPFL RCP model call"]
    Model --> Usable{"Usable structured response?"}
    Usable -->|no| Error["Classification error"]
    Usable -->|yes| Decision{"Relevant or somewhat relevant?"}
    Decision -->|yes| Accepted["Display accepted candidate"]
    Decision -->|no| Rejected["Display rejected candidate"]
```

Database search covers title, description, publisher, hosting platform,
uploader, geography, and dataset URL. PostgreSQL weights title highest and
orders matches by rank then update time. Both `tsvector` and `tsquery` use the
`english` configuration. The original query is preserved for the API, DataCite,
LLM classification, and display. A database error ends the request with HTTP
500; it is not treated as an empty result. Local retrieval is optimized for
primarily English metadata; complete bilingual search is not implemented.

Repository positive labels are `relevant` and `somewhat_relevant`. The prompt
judges relevance to the user query from repository metadata. It does not
independently validate health relevance, source authority, licence policy, or a
working data distribution.

Online repository results remain in React state. There is no repository-search save to
PostgreSQL and no automatic transition into the source collection pipeline.

### Normalized Repository Metadata Contract

Every provider result is normalized to the same ten fields before repository
classification:

| Field | Meaning |
| --- | --- |
| `Title` | Dataset title |
| `Geography` | Geographic coverage |
| `Date of publication` | Publication or issued date |
| `Dataset URL` | Dataset landing or canonical URL |
| `Disease(s)` | Explicit or extracted disease topics |
| `Size of dataset` | Record, byte, or coverage size when available |
| `Demographic information` | Population characteristics |
| `Sharing license` | Licence or rights metadata |
| `Modality of data` | Tabular, structured, image, audio, or other modality |
| `Description of dataset` | Dataset description or abstract |

Missing values are represented as `NA`; they are not treated as positive
evidence. The LLM also receives the user query and bounded repository fields
such as URL, publisher, description, and metadata-derived text.

### Provider Failure Handling

```mermaid
flowchart TD
    Providers["Configured providers"] --> Run["Call each provider"]
    Run --> Outcome{"Provider result"}
    Outcome -->|success| Merge["Merge normalized results"]
    Outcome -->|ValueError| Warning["Log + sanitized warning"]
    Merge --> Any{"At least one provider succeeded?"}
    Warning --> Any
    Any -->|yes| Response["Return partial/full results + warnings"]
    Any -->|no| Failure["Repository search failure"]
```

Only DataCite is configured by default, so its failure currently means all
providers failed.

## 3. Source Collection Pipeline

```mermaid
flowchart TD
    Start["POST /collector/collection-jobs"] --> Create["Create pending job"]
    Create --> Background["FastAPI background task"]
    Background --> Running["mark_collection_job_running()"]
    Running --> Collect["collect_source_with_report()"]
    Collect --> Discover["discover_source()"]
    Discover --> Limit["Limit pages by CollectorConfig"]
    Limit --> Analyze["Analyze each discovered record/page"]
    Analyze --> PageClassifier["Page classifier<br/>1-voter audit wrapper"]
    PageClassifier --> PageModel["1 EPFL RCP model call"]
    PageModel --> Accepted{"accepted=true?"}
    Accepted -->|no| Rejected["Count rejected"]
    Accepted -->|yes| Transient["Build transient CollectedDataset<br/>classification signals copied"]
    Transient --> Validate["validate_distribution()"]
    Validate --> Valid{"At least one valid distribution?"}
    Valid -->|no| Rejected
    Valid -->|yes| Result["Add eligible dataset to CollectionResult"]
    Result --> Complete["Persist dataset with complete_collection_job()"]
```

The page classifier prompt requires both an individual dataset/data resource and
health relevance. Its `dataset_signals` are copied into the `CollectedDataset`
for persistence and audit display.

`CollectionReport.accepted_count` is the number of eligible datasets retained
after distribution validation, not the number of positive page-classifier
responses. `rejected_count` includes inaccessible HTML pages, negative page
decisions, invalid structured URLs, and candidates left without a valid
distribution. Unexpected classifier or validation exceptions abort the job
instead of incrementing that counter.

## 4. Discovery Pipeline

```mermaid
flowchart TD
    SourceURL["Source URL"] --> Manager["discover_source()"]
    Manager --> Structured{"Structured adapter matches?"}
    Structured -->|CKAN| CKAN["CKAN records + resources"]
    Structured -->|Socrata| Socrata["Socrata catalog records + API"]
    Structured -->|data.json| DataJSON["DCAT/data.json records"]
    Structured -->|no| Sitemap["robots.txt / sitemap.xml"]
    Sitemap --> Generic["Generic page candidates"]
    CKAN --> Pages["DiscoveredPage list"]
    Socrata --> Pages
    DataJSON --> Pages
    Generic --> Pages
```

Structured metadata can be classified without downloading an HTML page. Generic
page candidates are fetched and extracted first. Dataverse is a proposed future
adapter and is not part of the active `ADAPTERS` tuple.

## 5. Distribution Validation

```mermaid
flowchart TD
    Distribution["DistributionCandidate URL"] --> Safe["open_public_http_url()"]
    Safe --> URLCheck["Validate initial destination"]
    URLCheck --> HEAD["HEAD request"]
    HEAD --> Redirect{"Redirect?"}
    Redirect -->|yes| RedirectCheck["Validate new destination"]
    RedirectCheck --> HEAD
    Redirect -->|no| Conclusive{"Conclusive response?"}
    Conclusive -->|no| GET["Bounded partial GET"]
    GET --> Redirect
    Conclusive -->|yes| Rules{"200-399, no error,<br/>non-HTML unless API?"}
    Rules -->|yes| Valid["ValidationResult.ok = true"]
    Rules -->|no| Invalid["ValidationResult.ok = false"]
```

Private, loopback, link-local, multicast, reserved, and unspecified destinations
are blocked for initial URLs and redirects. Validation is a lightweight network
and content-type check, not a complete dataset download.

## 6. Atomic Completion

```mermaid
flowchart TD
    Result["CollectionResult built outside transaction"] --> Complete["complete_collection_job(job_id, result)"]
    Complete --> Connection["Acquire one PostgreSQL connection"]
    Connection --> Tx["BEGIN transaction"]
    Tx --> Lock["Lock and verify running job"]
    Lock --> Source["Read source_url from job"]
    Source --> Save["Upsert every dataset and distribution"]
    Save --> Done["Mark job done with counters"]
    Done --> Commit["COMMIT"]
    Lock -. exception .-> Rollback["ROLLBACK"]
    Save -. exception .-> Rollback
    Done -. exception .-> Rollback
    Rollback --> ErrorTx["Separate transaction attempts job=error"]
```

The `done` status cannot commit unless every dataset write succeeds. If
PostgreSQL is completely unavailable, the separate attempt to persist `error`
can also fail.

## 7. Final Storage Condition

```text
The EPFL RCP page response is valid and accepted=true
AND
At least one considered distribution validates successfully
THEN
The eligible dataset is included in CollectionResult
AND
complete_collection_job() persists it while atomically marking the job done
```

An exact conflict on the normalized `dataset_url` updates the existing
`collected_datasets` record. The current schema does not deduplicate semantically
by DOI, title, version, or mirror.

For detailed contracts, see
[Classification Architecture](classification-architecture.md),
[Database Schema Diagram](database-schema-diagram.md), and the
[Dataset Collection & Quality Policy](dataset-collection-and-quality-policy.md).
