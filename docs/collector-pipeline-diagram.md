# Collector Pipeline Diagram

This document is a compact visual reference for the collector data flow and
repository-search metadata.

## Repository Search Metadata

Repository search results expose a business-facing `metadata` object. Each key is
always present; missing values are represented as `"NA"`.

```text
{
    "Title": "...",
    "Geography": "...",
    "Date of publication": "...",
    "Dataset URL": "...",
    "Disease(s)": "...",
    "Size of dataset": "...",
    "Demographic information": "...",
    "Sharing license": "...",
    "Modality of data": "...",
    "Description of dataset": "..."
}
```

## Repository Search Pipeline

```mermaid
classDiagram
    class RepositorySearchProvider {
        +str name
        +search(query) list
    }

    class DataCiteRepositorySearchProvider {
        +str name
        +search(query) list
        +_search_url(query) str
    }

    class DataCiteJSONResult {
        +dict attributes
        +str id
    }

    class RepositorySearchResult {
        +str title
        +str url
        +str source
        +str description
        +str publisher
        +str date
        +str doi
        +list keywords
        +float relevance_score
        +dict metadata
        +PageClassification classification
    }

    class RepositorySearchMetadata {
        +str Title
        +str Geography
        +str Date_of_publication
        +str Dataset_URL
        +str Diseases
        +str Size_of_dataset
        +str Demographic_information
        +str Sharing_license
        +str Modality_of_data
        +str Description_of_dataset
    }

    class RepositorySearchResponse {
        +list results
        +list warnings
    }

    class RepositorySearchWarning {
        +str message
        +str provider
    }

    RepositorySearchProvider <|.. DataCiteRepositorySearchProvider
    DataCiteRepositorySearchProvider --> DataCiteJSONResult : fetch_json()
    DataCiteJSONResult --> RepositorySearchResult : _datacite_result()
    DataCiteJSONResult --> RepositorySearchMetadata : _search_result_metadata()
    RepositorySearchResult "1" o-- "1" RepositorySearchMetadata : metadata
    RepositorySearchResponse "1" o-- "*" RepositorySearchResult : results
    RepositorySearchResponse "1" o-- "*" RepositorySearchWarning : warnings
```

`RepositorySearchMetadata` represents the exact JSON keys returned in
`RepositorySearchResult.metadata`: `Title`, `Geography`,
`Date of publication`, `Dataset URL`, `Disease(s)`, `Size of dataset`,
`Demographic information`, `Sharing license`, `Modality of data`, and
`Description of dataset`.

`PageSnapshot` stores the typed source values and derives the same metadata
contract only when it is exported or sent to a classifier.
`_PageHTMLParser` only extracts raw HTML fields; `extract_page()` converts those
raw fields into normalized `PageSnapshot` fields before classification.

## Discovery Adapter Pipeline

This is the adapter path used by `/collector/discover-url`, `/collector/collect-url`,
and async collection jobs.

```mermaid
flowchart TD
    SourceURL["source_url"]
    DiscoverSource["discover_source(source_url)"]
    AdapterOrder["ADAPTERS order<br/>1. CKAN<br/>2. Socrata<br/>3. data.json<br/>4. generic website"]
    Detect{"adapter.detect(source_url)?"}
    NextAdapter["try next adapter"]
    Discover["adapter.discover(source_url)"]
    DiscoveredPages["list[DiscoveredPage]"]

    SourceURL --> DiscoverSource --> AdapterOrder --> Detect
    Detect -- "no" --> NextAdapter --> Detect
    Detect -- "yes" --> Discover --> DiscoveredPages

    subgraph AdapterOutputs["DiscoveredPage fields"]
        CandidateIdentity["candidate identity<br/>url, discovery_method, priority"]
        BusinessFields["business fields for classification<br/>title, description, publisher, geography,<br/>date_of_publication, diseases, size_of_dataset,<br/>demographic_information, sharing_license, modality_of_data"]
        DistributionFields["distributions<br/>download/API candidates"]
        DiscoveryMetadata["discovery_metadata<br/>ckan_id, socrata_id, data_json_url,<br/>source_sitemap_url"]
    end

    DiscoveredPages --> CandidateIdentity
    DiscoveredPages --> BusinessFields
    DiscoveredPages --> DistributionFields
    DiscoveredPages --> DiscoveryMetadata

    DiscoverRoute["POST /collector/discover-url"]
    DiscoveryResponse["API response<br/>candidate pages only"]
    CollectRoute["POST /collector/collect-url<br/>or collection job"]
    SelectPages["selected pages<br/>max_pages_per_source"]
    StructuredCheck{"structured discovery data?"}
    DirectSnapshot["analyze_discovered_page()<br/>build PageSnapshot from DiscoveredPage"]
    FetchHTML["fetch_public_html()"]
    ExtractHTML["extract_page()<br/>_PageHTMLParser to PageSnapshot"]
    PageSnapshot["PageSnapshot<br/>normalized page + 10 business fields"]
    Classify["EnsemblePageClassifier.classify()<br/>3 LLM votes, >= 2 accept"]
    Accepted{"classification.accepted?"}
    Rejected["rejected<br/>not written to DB"]
    CollectedDataset["CollectedDataset"]
    Validate["validate distributions"]
    Save["save collected dataset<br/>if route requested save"]

    DiscoverRoute --> DiscoverSource
    DiscoveredPages --> DiscoveryResponse

    CollectRoute --> DiscoverSource
    DiscoveredPages --> SelectPages --> StructuredCheck
    StructuredCheck -- "yes" --> DirectSnapshot
    StructuredCheck -- "no" --> FetchHTML --> ExtractHTML
    DirectSnapshot --> PageSnapshot
    ExtractHTML --> PageSnapshot
    BusinessFields -. "copied into" .-> PageSnapshot
    DistributionFields -. "passed with page" .-> Classify
    DiscoveryMetadata -. "audit/API only" .-> DiscoveryResponse
    PageSnapshot --> Classify --> Accepted
    Accepted -- "no" --> Rejected
    Accepted -- "yes" --> CollectedDataset --> Validate --> Save
```

`discovery_metadata` is deliberately not part of the classification contract. It
keeps adapter/debug information about how the candidate was found. The classifier
reads the normalized `PageSnapshot` business fields plus distributions.

The default classifier is an `EnsemblePageClassifier`: it requires three distinct
OpenAI model names in `OPENAI_CLASSIFIER_MODEL_1`, `OPENAI_CLASSIFIER_MODEL_2`,
and `OPENAI_CLASSIFIER_MODEL_3`. A page is accepted when at least two successful
votes accept it. Final probabilities are averaged from the votes that carry the
majority decision, so an accepted page does not get dragged below threshold by a
rejected minority vote.

## Collector Pipeline

`PageHTMLParser` in this diagram represents the private `_PageHTMLParser`
implementation in `collector/extraction/extractor.py`.

```mermaid
classDiagram
    class FetchedPage {
        +str url
        +str final_url
        +int status_code
        +str content_type
        +str html
    }

    class PageHTMLParser {
        +list title_parts
        +list h1_parts
        +list heading_parts
        +list text_parts
        +list links
        +list json_ld
        +str canonical_url
        +str meta_description
        +str og_title
        +str og_description
        +str publisher
        +list geography
    }

    class PageSnapshot {
        +str url
        +str canonical_url
        +str title
        +str h1
        +str meta_description
        +str og_title
        +str og_description
        +tuple headings
        +str text
        +str publisher
        +tuple geography
        +str hosting_platform
        +str uploader
        +str date_of_publication
        +str dataset_url
        +tuple diseases
        +str size_of_dataset
        +tuple demographic_information
        +str sharing_license
        +tuple modality_of_data
        +str description_of_dataset
        +dict dataset_metadata()
        +tuple links
        +tuple json_ld
    }

    class LinkCandidate {
        +str url
        +str anchor
        +str nearby_text
        +str extension
        +bool same_domain
        +str dom_path
    }

    class DistributionCandidate {
        +str url
        +str format
        +float probability
        +str anchor
        +str extension
        +str mime_type
        +str nearby_text
        +bool same_domain
        +str dom_path
        +dict signals
        +str first_seen_at
        +str last_seen_at
        +str last_checked_at
    }

    class PageClassification {
        +bool accepted
        +float dataset_probability
        +float health_probability
        +HealthLabel health_label
        +dict dataset_signals
        +dict health_signals
    }

    class EnsemblePageClassifier {
        +list voters
        +int votes_required
        +classify(page, distributions) PageClassification
    }

    class PageClassificationVote {
        +str voter_id
        +bool accepted
        +float dataset_probability
        +float health_probability
        +HealthLabel health_label
        +dict dataset_signals
        +dict health_signals
    }

    class CollectedDataset {
        +str dataset_url
        +str title
        +str description
        +str publisher
        +tuple geography
        +str hosting_platform
        +str uploader
        +float dataset_probability
        +dict dataset_signals
        +float health_probability
        +HealthLabel health_label
        +dict health_signals
        +list distributions
        +list validation_results
        +str source_url
        +int database_id
        +str first_seen_at
        +str last_seen_at
        +str updated_at
    }

    class ValidationResult {
        +str url
        +str final_url
        +str format
        +bool ok
        +int http_status
        +str mime_type
        +int size_bytes
        +str etag
        +str last_modified
        +str content_disposition
        +str error
    }

    class CollectionReport {
        +int discovered_count
        +int analyzed_count
        +int accepted_count
        +int rejected_count
        +int invalid_distribution_count
        +tuple discovery_methods
    }

    class CollectionResult {
        +list datasets
        +CollectionReport report
    }

    FetchedPage --> PageHTMLParser : html parsed by
    PageHTMLParser --> PageSnapshot : extract_page() creates
    PageSnapshot "1" o-- "*" LinkCandidate
    PageSnapshot --> DistributionCandidate : extract_distributions()
    PageSnapshot --> EnsemblePageClassifier : classify() reads normalized fields
    EnsemblePageClassifier --> PageClassificationVote : collects 3 votes
    PageClassificationVote --> PageClassification : majority creates final verdict
    PageSnapshot --> CollectedDataset : accepted page becomes
    PageClassification --> CollectedDataset : scores copied into
    CollectedDataset "1" o-- "*" DistributionCandidate
    CollectedDataset "1" o-- "*" ValidationResult
    CollectionResult "1" o-- "*" CollectedDataset
    CollectionResult "1" o-- "1" CollectionReport
```
