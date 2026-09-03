# Collector Pipeline Diagram

> Current runtime flow, last verified 2026-09-02.

The application has two separate flows. Repository search classifies candidates
for display. Source collection decides whether discovered records can be stored.

## 1. Complete HTTP Flow

```mermaid
flowchart LR
    UI["React frontend"]
    Sources["/sources"]
    RepoSearch["/collector/search-repositories"]
    RepoClassify["/collector/classify-repository-result"]
    Jobs["/collector/collection-jobs"]
    JobStatus["/collector/collection-jobs/{id}"]
    Results["/collector/collected-datasets"]
    DB[(PostgreSQL)]

    UI --> Sources --> DB
    UI --> RepoSearch
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
    Query["User query"] --> Route["POST /collector/search-repositories"]
    Route --> Service["search_repository_metadata()"]
    Service --> DataCite["DataCiteRepositorySearchProvider"]
    DataCite --> API["DataCite /dois<br/>resource-type-id=dataset"]
    API --> Normalize["Normalize RepositorySearchResult"]
    Normalize --> Filter{"Title and HTTP(S) URL present?"}
    Filter -->|no| MetadataWarning["Drop result + warning"]
    Filter -->|yes| Candidates["Return candidates to frontend"]
    Candidates --> Workers["Progressive frontend workers"]
    Workers --> ClassifyRoute["POST /collector/classify-repository-result"]
    ClassifyRoute --> RepoClassifier["EnsembleRepositoryRelevanceClassifier"]
    RepoClassifier --> Models["3 distinct OpenAI model calls"]
    Models --> Quorum{"At least 2 usable votes?"}
    Quorum -->|no| Error["Classification error"]
    Quorum -->|yes| Majority{"At least 2 positive votes?"}
    Majority -->|yes| Accepted["Display accepted candidate"]
    Majority -->|no| Rejected["Display rejected candidate"]
```

Repository positive labels are `relevant` and `somewhat_relevant`. The prompt
judges relevance to the user query from repository metadata. It does not
independently validate health relevance, source authority, licence policy, or a
working data distribution.

Repository results remain in React state. There is no repository-search save to
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
    Analyze --> PageClassifier["EnsemblePageClassifier"]
    PageClassifier --> PageModels["3 distinct OpenAI model calls"]
    PageModels --> Accepted{"At least 2 accepted votes?"}
    Accepted -->|no| Rejected["Count rejected"]
    Accepted -->|yes| Candidate["Build CollectedDataset<br/>classification signals copied"]
    Candidate --> Validate["validate_distribution()"]
    Validate --> Valid{"At least one valid distribution?"}
    Valid -->|no| Rejected
    Valid -->|yes| Result["Add dataset to CollectionResult"]
    Result --> Complete["complete_collection_job()"]
```

The page classifier prompt requires both an individual dataset/data resource and
health relevance. Its `dataset_signals` are copied into the `CollectedDataset`
for persistence and audit display.

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
Page ensemble has at least 2 successful responses
AND
Page ensemble has at least 2 accepted votes
AND
At least one considered distribution validates successfully
THEN
The dataset is included in CollectionResult and persisted atomically
```

Exact-URL conflicts update the existing `collected_datasets` record. The current
schema does not deduplicate semantically by DOI, title, version, or mirror.

For detailed contracts, see
[Classification Architecture](classification-architecture.md),
[Database Schema Diagram](database-schema-diagram.md), and the
[Dataset Collection & Quality Policy](dataset-collection-and-quality-policy.md).
