# Classification Architecture

> Last verified: 2026-09-05. See the
> [Dataset Collection & Quality Policy](dataset-collection-and-quality-policy.md)
> for acceptance rules that are proposed but not yet fully enforced.

This document describes every runtime module under `collector/classification/`,
the values exchanged between them, and the two classification flows. Private
helpers are included when they validate, transform, or aggregate data.

## Module Map

```mermaid
flowchart LR
    Main["collector/main.py<br/>page collection"]
    Route["backend route<br/>repository classification endpoint"]
    Search["repository_search/service.py<br/>one normalized search result"]
    Factory["factory.py<br/>build default classifiers"]
    PageContract["page.py<br/>page contracts"]
    RepoContract["repository.py<br/>repository contracts"]
    PageAdapter["page_llm_classifier.py<br/>page payload and parser"]
    RepoAdapter["repository_llm_classifier.py<br/>repository payload and parser"]
    Ensemble["ensemble.py<br/>parallel voters and aggregation"]
    Client["llm_client.py<br/>generic HTTP JSON client"]
    RCP["providers/epfl_rcp.py<br/>default provider adapter"]
    DeepSeek["providers/deepseek.py<br/>optional direct provider adapter"]
    OpenAI["providers/openai.py<br/>optional provider adapter"]
    Prompts["prompts.py<br/>prompts and JSON schemas"]
    Facade["llm.py<br/>compatibility re-exports"]
    Models["storage/models.py<br/>PageSnapshot and DistributionCandidate"]

    Main --> Factory
    Route --> Factory
    Route --> Search
    Search --> RepoContract
    Factory --> Ensemble
    Factory --> PageAdapter
    Factory --> RepoAdapter
    Factory --> Client
    Factory --> RCP
    PageAdapter --> PageContract
    PageAdapter --> Client
    PageAdapter --> Models
    RepoAdapter --> RepoContract
    RepoAdapter --> Client
    RepoAdapter --> Models
    Ensemble --> PageContract
    Ensemble --> RepoContract
    Ensemble --> Models
    RCP --> Client
    RCP --> Prompts
    DeepSeek --> Client
    DeepSeek --> Prompts
    OpenAI --> Client
    OpenAI --> Prompts
    Facade -. "re-exports only" .-> Client
    Facade -. "re-exports only" .-> RCP
    Facade -. "re-exports only" .-> DeepSeek
    Facade -. "re-exports only" .-> OpenAI
    Facade -. "re-exports only" .-> PageAdapter
    Facade -. "re-exports only" .-> RepoAdapter
```

`classification/__init__.py` and `classification/providers/__init__.py` are
package markers. They do not run classification logic.

## Constructed Objects

```mermaid
classDiagram
    class PageClassifier {
        <<Protocol>>
        +classify(page, distributions) PageClassification
    }

    class RepositoryResultClassifier {
        <<Protocol>>
        +classify(page) RepositoryClassification
    }

    class LLMPageClassificationClient {
        <<Protocol>>
        +classify_page(payload) dict
    }

    class LLMProviderConfig {
        +str name
        +str endpoint_url
        +str api_key_env_var
        +str model_env_var
        +str default_model
        +RequestBodyBuilder request_body_builder
        +ResponseTextExtractor response_text_extractor
        +str auth_header
        +str auth_prefix
        +Mapping extra_headers
    }

    class HTTPJSONLLMClient {
        -LLMProviderConfig provider
        -str api_key
        -str model
        -float timeout_seconds
        -Callable request
        +classify_page(payload) dict
        -_request_body(payload) dict
    }

    class LLMPageClassifier {
        -LLMPageClassificationClient client
        +classify(page, distributions) PageClassification
    }

    class LLMRepositoryRelevanceClassifier {
        -LLMPageClassificationClient client
        +classify(page) RepositoryClassification
    }

    class EnsemblePageClassifier {
        -tuple voters
        -int votes_required
        -int minimum_successful_votes
        +classify(page, distributions) PageClassification
    }

    class EnsembleRepositoryRelevanceClassifier {
        -tuple voters
        -int votes_required
        -int minimum_successful_votes
        +classify(page) RepositoryClassification
    }

    class PageClassification {
        +bool accepted
        +dict dataset_signals
    }

    class RepositoryClassification {
        +RepositoryRelevanceLabel relevance_label
        +str reason
        +list missing_information
        +dict ensemble
        +bool accepted
    }

    PageClassifier <|.. LLMPageClassifier
    PageClassifier <|.. EnsemblePageClassifier
    RepositoryResultClassifier <|.. LLMRepositoryRelevanceClassifier
    RepositoryResultClassifier <|.. EnsembleRepositoryRelevanceClassifier
    LLMPageClassificationClient <|.. HTTPJSONLLMClient
    HTTPJSONLLMClient --> LLMProviderConfig
    LLMPageClassifier --> HTTPJSONLLMClient
    LLMRepositoryRelevanceClassifier --> HTTPJSONLLMClient
    EnsemblePageClassifier o-- LLMPageClassifier : one default voter
    EnsembleRepositoryRelevanceClassifier o-- LLMRepositoryRelevanceClassifier : one default voter
    LLMPageClassifier --> PageClassification
    LLMRepositoryRelevanceClassifier --> RepositoryClassification
```

The default factory creates one **EPFL RCP voter** using
`deepseek-ai/DeepSeek-V4-Flash-0731` by default. The ensemble classes remain
as compatibility and audit wrappers, both configured with thresholds 1 and 1.
The OpenAI provider adapter remains available but is not selected by default.

## Page Classification Flow

```mermaid
sequenceDiagram
    participant Caller as collector/main.py
    participant Factory as factory.py
    participant Ensemble as EnsemblePageClassifier
    participant Voter as 1 x LLMPageClassifier
    participant Client as HTTPJSONLLMClient
    participant Provider as providers/epfl_rcp.py
    participant API as EPFL RCP Chat Completions API

    Caller->>Factory: build_default_page_classifier()
    Factory-->>Caller: one-voter wrapper, thresholds 1 and 1
    Caller->>Ensemble: classify(page, distributions)
    Ensemble->>Voter: classify(page, distributions)
    Voter->>Voter: _build_llm_payload(...)
    Voter->>Client: classify_page(payload)
    Client->>Provider: use configured request_body_builder
    Client->>API: POST JSON to configured endpoint
    API-->>Client: Chat Completions response JSON
    Client->>Provider: use configured response_text_extractor
    Client-->>Voter: raw classification dict
    Voter->>Voter: _parse_page_classification(...)
    Voter-->>Ensemble: PageClassification
    Ensemble->>Ensemble: require 1 successful vote
    Ensemble->>Ensemble: accepted when accepted_votes >= 1
    Ensemble->>Ensemble: build the dataset audit summary
    Ensemble-->>Caller: final PageClassification
```

The wrapper still uses the generic ensemble implementation, but its default
voter list contains one EPFL RCP classifier. A failed or malformed model
response raises `PageClassificationError`; there is no fallback voter.

## Repository Classification Flow

```mermaid
sequenceDiagram
    participant Route as POST classify-repository-result
    participant Service as repository_search/service.py
    participant Factory as factory.py
    participant Ensemble as EnsembleRepositoryRelevanceClassifier
    participant Voter as 1 x LLMRepositoryRelevanceClassifier
    participant Client as HTTPJSONLLMClient
    participant API as EPFL RCP Chat Completions API

    Route->>Factory: build_default_repository_result_classifier()
    Route->>Service: classify_repository_result(result, classifier)
    Service->>Service: _repository_result_page(result)
    Service->>Ensemble: classify(PageSnapshot)
    Ensemble->>Voter: classify(page)
    Voter->>Voter: _build_repository_relevance_payload(page)
    Voter->>Client: classify_page(payload)
    Client->>API: POST prompt and JSON schema
    API-->>Client: label, reason, missing_information
    Client-->>Voter: raw dict
    Voter->>Voter: validate and construct RepositoryClassification
    Voter-->>Ensemble: classification
    Ensemble->>Ensemble: derive accepted from each label
    Ensemble->>Ensemble: accept when the single vote is positive
    Ensemble->>Ensemble: select label among decision-supporting votes
    Ensemble-->>Service: final RepositoryClassification
    Service-->>Route: RepositorySearchResult with classification
```

For repository results, `relevant` and `somewhat_relevant` are positive votes.
`not_relevant` and `insufficient_information` are negative votes. When labels
tie inside the group that supports the binary decision, the conservative order
is `not_relevant`, `insufficient_information`, `somewhat_relevant`, `relevant`.

### Strict `missing_information` contract

`missing_information` is meaningful only when the classifier cannot make a
reliable relevance decision. The label and list must therefore agree:

| Label | `missing_information` | Valid? |
|---|---|---|
| `relevant` | `[]` | Yes |
| `somewhat_relevant` | `[]` | Yes |
| `not_relevant` | `[]` | Yes |
| `insufficient_information` | one or more nonempty strings | Yes |
| `insufficient_information` | `[]` | No |
| any other label | a nonempty list | No |

The prompt asks the model to follow this contract, and the backend validates it
again. A contradiction is not silently corrected: the EPFL RCP response becomes
a `PageClassificationError`, and there is no fallback voter.

## Function Inventory

### `factory.py`

| Function | Parameters | Returns | Calls and reuse |
|---|---|---|---|
| `build_default_page_classifier` | none | `PageClassifier` | Constructs one EPFL RCP provider config, HTTP client, and `LLMPageClassifier`; wraps it in `EnsemblePageClassifier(1, 1)` for the existing audit contract. |
| `build_default_repository_result_classifier` | none | `RepositoryResultClassifier` | Constructs the corresponding EPFL RCP repository classifier in `EnsembleRepositoryRelevanceClassifier(1, 1)`. |

### `llm_client.py`

| Function or method | Parameters | Returns | Role |
|---|---|---|---|
| `LLMPageClassificationClient.classify_page` | normalized `payload` | raw classification `dict` | Protocol shared by both concrete LLM classifiers. |
| `extract_responses_output_text` | decoded Responses API envelope | output text | Accepts top-level `output_text` or nested message `output_text`; ignores preceding DeepSeek `reasoning_text`. |
| `extract_chat_completions_message_text` | decoded Chat Completions envelope | output text | Extracts the assistant text from `choices[].message.content`; used by EPFL RCP. |
| `HTTPJSONLLMClient.__init__` | `provider`, optional `api_key`, `model`, `timeout_seconds`, injectable `request` | client | Explicit key/model override environment lookup. The injectable request makes network behavior testable. |
| `HTTPJSONLLMClient.classify_page` | `payload` | decoded classification object | Resolves API key, builds headers and request body, performs POST, decodes provider response, extracts text, parses the second JSON layer, and rejects non-object output. |
| `HTTPJSONLLMClient._request_body` | `payload` | provider-specific body | Resolves model from explicit value, provider model environment variable, then provider default; invokes `request_body_builder`. |

`LLMProviderConfig` carries all provider-specific HTTP decisions. Its two
callables are reused by the generic client: `request_body_builder(payload,
model)` builds the outgoing body, while `response_text_extractor(response)`
finds the model's textual JSON output in the provider response.

### Provider adapters

| Function | Parameters | Returns | Role |
|---|---|---|---|
| `epfl_rcp_chat_completions_provider_config` | display `name`, model env name, default model | `LLMProviderConfig` | Selects EPFL RCP authentication, Chat Completions endpoint, page builder, and response extractor. |
| `epfl_rcp_repository_relevance_provider_config` | same parameters | `LLMProviderConfig` | Selects the EPFL RCP repository relevance builder. |
| `deepseek_responses_provider_config` | display `name`, model env name, default model | `LLMProviderConfig` | Selects DeepSeek authentication, endpoint, page builder, and shared Responses extractor. |
| `deepseek_repository_relevance_provider_config` | same parameters | `LLMProviderConfig` | Selects the DeepSeek repository relevance builder. |
| OpenAI and direct DeepSeek provider functions | same parameters | `LLMProviderConfig` | Remain available for explicit use but are not selected by the default factory. |

### `prompts.py`

| Function | Parameters | Returns | Role |
|---|---|---|---|
| `_build_epfl_rcp_chat_completions_request_body` | page `payload`, `model` | EPFL RCP request body | Adds page system prompt, user JSON, embedded schema, and JSON-object response mode. |
| `_build_epfl_rcp_repository_relevance_request_body` | repository `payload`, `model` | EPFL RCP request body | Adds repository prompt, user JSON, embedded schema, and JSON-object response mode. |
| `_build_chat_completions_request_body` | payload, model, prompt, schema | Chat Completions body | Centralizes `messages`, the embedded schema instruction, and JSON-object response mode. |
| `_build_openai_responses_request_body` | page `payload`, `model` | OpenAI request body | Adds page system prompt, user JSON, and strict page JSON schema. |
| `_build_openai_repository_relevance_request_body` | repository `payload`, `model` | OpenAI request body | Adds repository relevance prompt and strict repository schema. |
| `_build_deepseek_responses_request_body` | page `payload`, `model` | DeepSeek request body | Reuses the page prompt and schema without the undocumented OpenAI `strict` flag. |
| `_build_deepseek_repository_relevance_request_body` | repository `payload`, `model` | DeepSeek request body | Reuses the repository prompt and schema without the `strict` flag. |
| `_build_responses_request_body` | payload, model, prompt, schema options | Responses API body | Centralizes the common system/user messages and JSON-schema output shape. |
| `_system_prompt` | none | string | Defines an accepted page as an individual, health-relevant dataset/resource/API dataset and treats page data as untrusted evidence. |
| `_repository_relevance_system_prompt` | none | string | Defines relevance to the user query, four labels, missing-information behavior, and prompt-injection protection. |
| `_classification_schema` | none | JSON Schema | Requires `accepted` and `dataset_signals`, with exact `reason` and `evidence` strings. |
| `_repository_relevance_schema` | none | JSON Schema | Requires `label`, `reason`, and `missing_information`; forbids extra top-level fields. |

### `page_llm_classifier.py`

| Function or method | Parameters | Returns | Role |
|---|---|---|---|
| `LLMPageClassifier.__init__` | a client implementing `classify_page` | classifier | Dependency injection; it does not know which provider is used. |
| `LLMPageClassifier.classify` | `PageSnapshot`, list of `DistributionCandidate` | `PageClassification` | Builds payload, calls client, preserves known classification errors, wraps unexpected client errors, parses output. |
| `_build_llm_payload` | `page`, `distributions` | JSON-safe dict | Copies normalized page fields and metadata; applies field-specific string limits and caps headings at 20, page text at 4,000 characters, and distributions at 10. |
| `_parse_page_classification` | raw dict | `PageClassification` | Requires a boolean decision and one `dataset_signals` object containing exactly `reason` and `evidence` strings. |
| `_required_bool` | object and field name | bool | Rejects missing values and non-booleans; it does not use `bool(value)`. |
| `_required_json_object` | object and field name | dict | Requires an object and delegates recursive JSON-safety validation. |
| `_required_signal_object` | object and field name | dict | Requires exactly `reason` and `evidence`, both strings. |
| `_json_safe_object` | dict and field name | dict | Converts low-level type/value failures into `PageClassificationError`. |
| `_json_safe_value` | any value | JSON-safe value | Recursively accepts null, strings, booleans, finite numbers, lists, and string-keyed dicts; rejects unsupported values and non-finite numbers. |

### `repository_llm_classifier.py`

| Function or method | Parameters | Returns | Role |
|---|---|---|---|
| `LLMRepositoryRelevanceClassifier.__init__` | shared LLM client | classifier | Uses the same transport abstraction as page classification. |
| `LLMRepositoryRelevanceClassifier.classify` | `PageSnapshot` | `RepositoryClassification` | Builds bounded query-aware payload, calls client, and validates the result. |
| `_build_repository_relevance_payload` | `page` | dict | Requires `search_query`; bounds query, URLs, title, description, publisher, text, and all normalized metadata values. |
| `_repository_metadata_value` | metadata `key`, `value` | bounded string | Applies field-specific size limits; reused for every metadata entry. |
| `_parse_repository_relevance_classification` | raw dict | `RepositoryClassification` | Validates label, reason, and list; requires missing details for `insufficient_information` and rejects them for every other label. |
| `_required_relevance_label` | raw object and field name | supported label | Rejects unknown labels before the dataclass is created. |
| `_required_non_empty_string` | raw object and field name | stripped string | Rejects empty/non-string/overlong reasons. |
| `_required_string_list` | raw object and field name | normalized list | Rejects wrong types, too many entries, and overlong entries. |

### `page.py` and `repository.py`

| Element | Parameters or fields | Reuse |
|---|---|---|
| `PageClassificationError` | message and chained cause | Common visible failure type across transport, parsing, voters, factory, service, and route. |
| `PageClassification` | `accepted`, `dataset_signals` | Returned by each page voter and by the final page ensemble. |
| `PageClassificationVote` | same result plus `voter_id` | Internal ensemble audit record. |
| `PageClassifier.classify` | `page`, `distributions` | Structural contract implemented by individual and ensemble page classifiers. |
| `RepositoryClassification` | label, reason, missing data, ensemble | Strips/validates semantic data and derives `accepted`; returned by individual and ensemble classifiers. |
| `RepositoryClassificationVote` | repository result plus `voter_id` | Internal repository ensemble record; also derives `accepted`. |
| `RepositoryResultClassifier.classify` | `page` | Structural contract implemented by individual and ensemble repository classifiers. |
| `_validate_relevance_label` | runtime value | Rejects values outside the four supported labels; this complements the non-runtime `Literal` annotation. |
| `_normalized_missing_information` | label and list | Deduplicates/strips values; requires a nonempty list for `insufficient_information` and rejects a nonempty list for every other label. |

The value-object methods and accessors are also active parts of the contract:

| Method or object | Parameters | Effect or returned value |
|---|---|---|
| `RepositoryClassification.__post_init__` | the fields passed to the dataclass constructor | Strips and requires `reason`, normalizes missing information, and derives the non-init `accepted` field from `relevance_label`. |
| `RepositoryClassificationVote.__post_init__` | the fields passed to the vote constructor | Applies the same invariants to each ensemble vote. |
| `EnsemblePageClassifier.voter_ids` | none | Reconstructs the configured voter IDs as a tuple for inspection/tests. |
| `EnsemblePageClassifier.votes_required` | none | Exposes the validated positive-vote threshold. |
| `EnsemblePageClassifier.minimum_successful_votes` | none | Exposes the validated quorum. |
| Repository ensemble accessors | none | Expose the same three values for repository classification. |
| `_VoteOutcome` | `voter_id`, optional page vote, optional error | Represents exactly one successful page vote or one page-voter failure. |
| `_RepositoryVoteOutcome` | `voter_id`, optional repository vote, optional error | Equivalent repository-voter result. |

### Compatibility and package files

| File | Runtime effect |
|---|---|
| `llm.py` | Imports and re-exports the public client, provider, and concrete-classifier names. It contains no classification branch of its own. Existing imports can keep using this facade while new code imports the owning module directly. |
| `classification/__init__.py` | Declares the classification package and contains only its package description. |
| `providers/__init__.py` | Declares the provider-adapter package; it currently does not re-export provider names. |

### `ensemble.py`

| Function or method | Parameters | Returns | Role |
|---|---|---|---|
| `_validate_voting_thresholds` | voter count, required positive votes, minimum successful votes | normalized minimum | Enforces both thresholds within voter count and prevents the minimum-successful threshold from being lower than the acceptance threshold. |
| Both ensemble constructors | voters, `votes_required`, `minimum_successful_votes` | ensemble | Require at least one voter, unique IDs, immutable voter storage, valid thresholds. |
| Both `classify` methods | page and optionally distributions | final classification | Gather outcomes, separate successes/failures, enforce quorum, compute binary decision, select supporting votes, and build audit summary. |
| Both `_classify_voters` methods | input objects | ordered outcomes | Run every voter concurrently with one worker per voter. `executor.map` preserves configured voter order in returned outcomes. |
| `_classify_voter` | `(voter_id, classifier)`, page, distributions | `_VoteOutcome` | Converts successful classifications into votes and expected page failures into error outcomes. |
| `_classify_repository_voter` | `(voter_id, classifier)`, page | `_RepositoryVoteOutcome` | Same conversion; also treats repository dataclass `ValueError` as a voter failure. |
| `_minimum_votes_error` | minimum, success count, failures | error message | Includes each failed voter ID and error when quorum is not reached. |
| `_ensemble_summary` / `_vote_summary` | page votes, failures, thresholds and decision | audit dict | Builds the dataset-classification audit view and preserves each voter's signals. |
| `_repository_ensemble_summary` / `_repository_vote_summary` | repository votes and decision data | audit dict | Preserves labels, reasons, missing information, failures, and voter IDs. |
| `_decision_votes` | page votes and final boolean | supporting page votes | Rejects impossible state where no successful vote supports the final decision. |
| `_repository_decision_votes` | repository votes and final boolean | supporting repository votes | Same invariant for repository decisions. |
| `_decision_reason` / `_repository_decision_reason` | accepted flag, votes, threshold | reason code | Returns `enough_accept_votes`, `rejected_by_majority`, or `insufficient_accept_votes`. |
| `_majority_relevance_label` | supporting repository votes | final label | Counts labels and resolves ties conservatively. |
| `_relevance_reason` | supporting votes, final label | reason string | Takes the first reason from a vote with the selected label. |
| `_combined_missing_information` | supporting votes, final label | list | Returns a stable deduplicated union only for `insufficient_information`. |

## Reused Parameter Traces

```mermaid
flowchart LR
    ModelEnv["RCP_CLASSIFIER_MODEL"] --> Load["HTTPJSONLLMClient._request_body"] --> Model["configured or default model"]
    Model --> Builder["request_body_builder payload plus model"] --> APIBody["EPFL RCP body.model"]

    VoterId["voter_id"] --> Pair["voter tuple"] --> Outcome["vote or failure outcome"] --> Audit["decision_voter_ids, voters, failures"]

    Page["PageSnapshot"] --> PagePayload["bounded page payload"] --> RawPage["accepted and signals"] --> PageVote["PageClassificationVote"] --> PageDecision["ensemble PageClassification"]

    Query["search_query"] --> RepoPage["PageSnapshot.search_query"] --> RepoPayload["repository payload"] --> Label["relevance_label"] --> Derived["derived accepted boolean"] --> RepoDecision["ensemble RepositoryClassification"]

    Thresholds["votes_required=1 and minimum_successful_votes=1"] --> Validate["_validate_voting_thresholds"] --> Both["both audit wrappers"]
```

The important distinction is:

- `votes_required` controls how many positive votes are needed to accept;
- `minimum_successful_votes` controls how many classifiers must return a usable
  response before any decision is allowed.

## Verified Boundaries and Open Decisions

1. Classification code performs no database writes and contains no destructive
   database operation. It returns domain objects to its callers.
2. LLM output is validated without truthy coercions or silent default objects.
   Invalid response JSON, wrong top-level type, unsupported labels, wrong signal
   shapes, and insufficient quorum all remain visible errors.
3. The repository prompt currently evaluates **relevance to the query only**.
   Unlike the page prompt, it does not independently require the result to be a
   global-health dataset. This behavior is explicit in the prompt and tests. It
   is correct only if repository providers/search queries already define the
   health boundary; otherwise a query-relevant non-health dataset can pass.
4. The page contract keeps one `dataset_signals` audit object. It explains the
   complete dataset decision, including dataset identity and health relevance;
   `accepted` remains the only value used for the binary decision.
5. Both payload builders apply field-specific string limits. The page payload
   also caps heading count, page text, and distribution count; the repository
   payload separately bounds its query, normalized metadata, and result fields.
6. The default uses one DeepSeek model through the EPFL RCP endpoint and API-key
   path. There is no provider or model fallback, so any failed or malformed
   response fails that classification.
7. The repository route allows two classifications at once. Each starts one
   EPFL RCP call, so at most two repository LLM HTTP calls run concurrently.
