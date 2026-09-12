# Global Health Pipeline — Corrected Version

Verified against the local code on September 11, 2026.

The three blocks run in sequence. Manual collection enters directly into the third block. The diagrams use Mermaid, and their source files remain editable.

Both classification stages run DeepSeek, Gemma Meditron, and Apertus Meditron in parallel. Two positive votes are required, and all three responses must be usable.

## 1. Search

Editable source: `01-search.mmd`.

```mermaid
flowchart TD
    A(["User clicks Search"])
    A --> B["Frontend: searchRepositories"]
    B --> C["POST /collector/search-datasets"]
    C --> D["Identify the user<br/>Check the search quota"]
    D --> E["create_search_session<br/>Store the original query and its owner"]
    E --> F["normalize_dataset_search_query<br/>For local search only"]
    F --> G["search_collected_datasets<br/>Search PostgreSQL"]
    G --> H{"Local results?"}
    G -.->|"PostgreSQL error"| ERR["Search failed<br/>Return to frontend — no DataCite call"]
    H -->|"Yes"| I["Complete the session<br/>origin = database"]
    I --> J["Frontend: display local datasets"]
    J --> END1(["End search"])
    H -->|"No"| K["_search_online_repositories<br/>With the original query"]
    K --> L["search_repository_metadata"]
    L --> M["DataCiteRepositorySearchProvider.search<br/>Up to 10 candidates"]
    M --> N["Filter and bound metadata"]
    N --> O["PostgreSQL transaction<br/>Store repository_candidates<br/>Complete the session: completed or partial"]
    O --> P["Return origin = online<br/>search_id + candidate_id + warnings"]
    L -.->|"Provider failure"| ERR2["Session failed<br/>Return to frontend"]
    O -.->|"Persistence failure"| ERR2
    P --> Q{"At least one candidate?"}
    Q -->|"No"| END2(["Display no results"])
    Q -->|"Yes"| NEXT(["BLOCK 2 — Classify each candidate"])
```

## 2. Classification and Collection Reservation

Editable source: `02-classification.mmd`.

```mermaid
flowchart TD
    A(["BLOCK 2 — Stored candidates"])
    A --> B["Frontend: classifyRepositoryCandidates<br/>Up to 2 candidates concurrently"]
    B --> C["POST /collector/<br/>repository-candidates/{candidate_id}/classify"]
    C --> D["Identify the user<br/>Load the user's candidate from PostgreSQL"]
    D --> E{"Candidate state?"}
    E -->|"pending, or error with retry=true"| F["Check the classification quota<br/>start_candidate_classification<br/>Atomic reservation"]
    E -->|"accepted"| ACCEPT
    E -->|"rejected"| REJECT
    E -->|"classifying, or error without retry"| CONFLICT["Return HTTP 409<br/>In progress or explicit retry required"]
    F --> G["If reserved: rebuild<br/>RepositorySearchResult, then PageSnapshot<br/>from stored data"]
    G --> H["LLM relevance classification<br/>Compare metadata with the original query<br/>3-model vote"]
    H --> I{"Candidate accepted?"}
    H -.->|"Model or response error"| ERR["Store classification_status = error<br/>Return to frontend"]
    I -->|"No"| REJECT["Store or return rejected<br/>No collection"]
    I -->|"Yes"| SAVE["Store classification_status = accepted"]
    SAVE --> ACCEPT["_reserve_automatic_collection"]
    SAVE -.->|"Persistence failure"| ERR
    ACCEPT --> R["reserve_repository_candidate_collection_job<br/>Atomic reservation by candidate and URL"]
    R -.->|"Reservation failure"| SCHEDERR["Return automatic_collection.state = error"]
    R --> J{"URL already associated<br/>with a saved dataset?"}
    J -->|"Yes"| SAVED["Return state = saved<br/>No new collection"]
    J -->|"No"| K{"Existing pending or running job?"}
    K -->|"Yes"| EXIST["Return the active job<br/>Do not schedule another job"]
    K -->|"No"| NEW["Create collection_jobs<br/>kind = repository_candidate<br/>status = pending"]
    NEW --> SCHEDULE["_schedule_collection_job<br/>background_tasks.add_task"]
    SCHEDULE --> NEXT(["BLOCK 3 — Run collection"])
    EXIST --> FOLLOW["Frontend: track the existing job<br/>See tracking in block 3"]
    SCHEDULE -.->|"HTTP response before job completion"| FOLLOW
```

## 3. Collection, Persistence, and Tracking

Editable source: `03-collection-and-tracking.mmd`.

```mermaid
flowchart TD
    AUTO(["From block 2<br/>Scheduled candidate job"])
    MANUAL(["User starts collection from a source"])
    MANUAL --> M1["POST /collector/collection-jobs"]
    M1 --> M2["Identify the user<br/>Check the collection quota"]
    M2 --> M3["Create a pending job<br/>kind = source"]
    M3 --> M4["_schedule_collection_job<br/>HTTP 202 response"]
    AUTO --> RUN["_run_collection_job"]
    M4 --> RUN
    RUN --> MARK["mark_collection_job_running<br/>Continue only if the transition succeeds"]
    MARK --> KIND{"Job type?"}
    KIND -->|"repository_candidate"| C1["collect_repository_candidate_with_report"]
    C1 --> C2["Normalize candidate_url<br/>Create one DiscoveredPage"]
    C2 --> C3["collect_source_with_report<br/>Limit discovery to this page"]
    KIND -->|"source"| S1["collect_source_with_report"]
    S1 --> S2["discover_source<br/>CKAN · Socrata · data.json · website"]
    S2 --> S3["Select pages to analyze<br/>Current maximum: 5 per source"]
    C3 --> PAGE
    S3 --> PAGE["_collect_discovered_page_with_report<br/>For each selected page"]
    PAGE --> STRUCT{"Structured metadata<br/>already available?"}
    STRUCT -->|"Yes"| STRUCTURED["analyze_discovered_page<br/>Build PageSnapshot<br/>Reuse supplied distributions"]
    STRUCT -->|"No"| FETCH["fetch_public_html<br/>Fetch the target page"]
    FETCH --> EXTRACT["analyze_html_page<br/>extract_page, then extract_distributions"]
    STRUCTURED --> CLASSIFY["page_classifier.classify<br/>Page + distribution candidates<br/>Individual health-relevant dataset?<br/>3-model vote"]
    EXTRACT --> CLASSIFY
    CLASSIFY --> ACCEPTED{"Page accepted?"}
    ACCEPTED -->|"No"| REJECT["Count the page as rejected"]
    ACCEPTED -->|"Yes"| VALIDATE["validate_distribution<br/>HEAD, then partial GET if needed<br/>Current maximum: 1 tested distribution"]
    VALIDATE --> VALID{"At least one tested<br/>distribution is valid?"}
    VALID -->|"No"| REJECT
    VALID -->|"Yes"| KEEP["Add the dataset and its<br/>validated distributions to the result"]
    KEEP --> MORE{"Another selected page?"}
    REJECT --> MORE
    MORE -->|"Yes"| PAGE
    MORE -->|"No"| RESULT["CollectionResult + report<br/>With zero, one, or more datasets"]
    RESULT --> SAVE["complete_collection_job<br/>One PostgreSQL transaction:<br/>save datasets and move the job to done"]
    SAVE --> DONE["job = done<br/>saved_count = number of saved datasets"]
    FETCH -.->|"Exception"| ERROR
    CLASSIFY -.->|"Classification error"| ERROR
    S2 -.->|"Discovery error"| ERROR
    SAVE -.->|"Transaction failure"| ERROR
    ERROR["mark_collection_job_error<br/>job = error if the database write succeeds"]
    AUTO -.-> POLL
    M4 -.-> POLL
    EXIST(["Active job reused in block 2"]) -.-> POLL
    POLL["Frontend: poll periodically<br/>GET /collector/collection-jobs/{id}"]
    POLL --> STATUS{"Received state?"}
    STATUS -->|"pending or running"| WAIT["Wait, then poll again<br/>Within the frontend tracking limit"]
    WAIT --> POLL
    STATUS -->|"done, saved_count > 0"| REFRESH["GET /collector/collected-datasets<br/>Refresh the catalog and display success"]
    STATUS -->|"done, saved_count = 0"| EMPTY["Display: collection completed<br/>without a valid dataset"]
    STATUS -->|"error"| UIERROR["Display the error"]
    POLL -.->|"Tracking failure or timeout"| TRACKERR["Display a tracking error<br/>The backend job may continue"]
```

## Reading Notes

- Persistence covers metadata and links, not complete dataset files.
- Tasks run inside the backend process. On restart, searches, classifications, and jobs left active are marked as errors.
- A reused active job continues its existing execution; it is not scheduled again.
- A new request can create another attempt after a job finishes without a dataset or with an error, as long as the dataset remains absent.
- If a classification reservation loses a race against a concurrent request, the server reloads the candidate state before responding.
- Error branches show the main cases. `_run_collection_job` handles every exception during job execution, including extraction and validation failures. A PostgreSQL outage can prevent the error itself from being recorded.
- Access denials, exhausted quotas, and invalid requests stop the affected request before expensive processing begins.
- The limits of 5 pages and 1 distribution reflect the collector's current configuration.
