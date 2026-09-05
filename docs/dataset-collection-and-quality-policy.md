# Dataset Collection & Quality Policy

| Field | Value |
| --- | --- |
| Project | Global Health Dataset Catalog |
| Document version | 0.2 |
| Status | Draft for product and data-governance approval |
| Last reviewed | 2026-09-02 |
| Applies to | Repository search, source collection, classification, validation, and catalog publication |
| Policy owner | To be assigned |
| Technical owner | To be assigned |

## 1. Purpose

This policy defines which dataset records belong in the Global Health Dataset
Catalog, how their quality is assessed, and which decisions require human review.
It is the business and data-governance counterpart to the technical design and
architecture documents.

The policy has four goals:

1. keep the catalog focused on usable global-health data;
2. make acceptance and rejection decisions explainable and repeatable;
3. prevent repository search results from being treated as approved datasets;
4. identify the controls that are enforced today and those still requiring
   implementation.

This document governs metadata and links. The current project does not download
or store dataset files.

## 2. Status and Interpretation

This is a draft policy. Statements marked **Current** describe behavior confirmed
in the code as of the review date. Statements marked **Required policy** define
the recommended catalog rule, whether or not it is implemented yet. Statements
marked **Decision required** need approval from the policy owner.

The terms **must**, **must not**, **should**, and **may** express policy strength:

- **must / must not**: required for compliance;
- **should / should not**: expected unless a documented exception exists;
- **may**: optional.

If the code and this policy disagree, the discrepancy must be recorded as an
implementation gap. A draft policy must not be represented as an enforced
technical control.

## 3. Scope

### In scope

- candidate datasets returned by repository APIs;
- pages and records discovered from CKAN, Socrata, `data.json`/DCAT,
  sitemaps, and generic websites;
- LLM classification decisions and their audit evidence;
- dataset metadata and provenance;
- downloadable files and API distributions;
- link validation, deduplication, review, publication, and withdrawal;
- quality measurement and periodic revalidation.

### Out of scope

- downloading or hosting dataset files;
- validating the scientific correctness of every value inside a dataset;
- granting legal permission to use a third-party dataset;
- clinical decision-making or medical advice;
- production infrastructure, authentication, backup, and incident response,
  except where they affect catalog quality.

## 4. Definitions

| Term | Definition |
| --- | --- |
| Candidate | A possible dataset returned by discovery or repository search. It is not yet an approved catalog record. |
| Dataset | A discrete collection of structured data, or an API-backed data resource, described as one identifiable resource. |
| Catalog or portal page | A page that lists or searches many datasets. It is a source for discovery, not an individual dataset. |
| Source | The portal, website, or repository used as the starting point for discovery. |
| Publisher | The organization responsible for producing or publishing the dataset. |
| Hosting platform | A service that hosts data but is not necessarily its publisher, such as Kaggle. |
| Distribution | A file or API through which the underlying data can be accessed. |
| Validated distribution | A distribution whose HTTP probe succeeded and did not return an HTML page in place of data. |
| Provenance | Evidence identifying where the dataset came from, who published it, and how it was discovered. |
| Approved record | A candidate that passes all mandatory gates or receives a documented human exception. |
| Published catalog | The collection of records shown to end users as accepted datasets. |

## 5. Core Principles

1. **Search is discovery, not approval.** Query relevance alone never makes a
   candidate an approved catalog record.
2. **Publisher and host are different concepts.** A hosting platform must not be
   presented as the original publisher unless the metadata explicitly supports it.
3. **Structured evidence is preferred.** Repository metadata, Schema.org
   `Dataset`, DCAT, and direct distribution metadata should be preferred over
   weak keyword matches.
4. **Missing information is not positive evidence.** Unknown publisher,
   geography, license, or population must remain unknown.
5. **Automated decisions must be auditable.** Voter decisions, reasons, evidence,
   discovery method, validation results, and timestamps must be retained.
6. **Catalog quality takes priority over result count.** Uncertain records should
   be reviewed or withheld instead of silently accepted.
7. **The catalog links to data; it does not certify scientific validity.** The UI
   and API should not imply endorsement of a dataset's methodology or findings.

## 6. Source Trust Policy

Source trust is based on provenance, not only on the domain that hosts a record.

| Tier | Source type | Examples | Required treatment |
| --- | --- | --- | --- |
| A — authoritative | Intergovernmental health bodies, official national public-health/statistical agencies, or the original institutional publisher | WHO or an official government health portal | May be automatically approved when all dataset, health, metadata, and distribution gates pass. |
| B — curated repository | Recognized research or humanitarian repository with a named publisher/depositor and clear record provenance | DataCite-indexed repositories, Dataverse, institutional repositories, HDX | May be automatically approved when provenance identifies the underlying publisher and all other gates pass. |
| C — community or commercial host | A platform that can contain both authoritative and user-uploaded material | Kaggle and similar platforms | Must receive human review unless publisher identity, provenance, license, and data access are independently verifiable. |
| D — unknown or unverifiable | Anonymous pages, URL shorteners without traceable destination, copied datasets with no attribution, or sources with conflicting identity | Varies | Must not be published until provenance is resolved. |

**Required policy:** The word "official" must be used only for Tier A records or
when Tier B metadata clearly identifies an authoritative original publisher.

**Current:** The code recognizes WHO domains as a known publisher and Kaggle as a
hosting platform, but it does not enforce a complete source-tier policy.

**Decision required:** Approve the source tiers and nominate the person or team
allowed to grant exceptions.

## 7. Acceptance Gates

An approved catalog record must satisfy every mandatory gate below. A failure is
either a rejection or a human-review case; it must not be silently converted into
acceptance.

| Gate | Required policy | Current enforcement | Result when unmet |
| --- | --- | --- | --- |
| G1 — identifiable resource | The candidate describes one identifiable dataset, downloadable data resource, or API-backed dataset, not only a catalog, article, dashboard, or document. | The page-classification prompt asks the EPFL RCP classifier to make this distinction. | Reject, or review if the evidence is ambiguous. |
| G2 — health relevance | The dataset materially concerns health, public health, clinical care, epidemiology, disease, mortality, morbidity, vaccination, health systems, or a closely related topic. | Enforced by the page-classification prompt. Not independently enforced by repository relevance classification. | Reject from the health catalog. |
| G3 — provenance | A publisher or responsible depositor and the discovery source can be identified. Hosting platform and publisher must remain separate. | Source URL and discovery method are stored; publisher may be empty. | Review when publisher is missing; reject when provenance is unverifiable. |
| G4 — usable data access | At least one machine-usable file or API distribution is present. A PDF, ordinary HTML page, or image alone is insufficient. | Persistent collection requires at least one validated distribution. | Do not publish as an accessible dataset. |
| G5 — technical validation | At least one distribution responds successfully and is not an HTML error or landing page masquerading as data. | `HEAD` is tried first, followed by a bounded partial `GET` when needed. Successful 2xx/3xx non-HTML responses pass. | Reject from automatic storage or send to review. |
| G6 — minimum metadata | Dataset URL and title must be present. Publisher and source must be present before public publication. Unknown optional fields must remain explicitly unknown. | Dataset URL and title are populated; publisher can be blank. Repository results require a title and HTTP(S) URL. | Withhold or review if a publication-critical field is missing. |
| G7 — lawful and safe description | Available metadata must not indicate unlawful access, exposed credentials, or direct publication of sensitive person-level health data without an appropriate access mechanism. | No complete automated control exists. | Quarantine and require human review. |
| G8 — duplicate control | The record must not duplicate an existing dataset identity. Versions and mirrors must be linked intentionally. | Stored datasets are unique by exact normalized `dataset_url`; distribution candidates are deduplicated by canonical URL and format within extraction. | Merge, link as a version/mirror, or reject the duplicate. |

### Automatic acceptance rule

A candidate may be accepted automatically only when:

- G1 through G8 pass;
- its source is Tier A or Tier B;
- the EPFL RCP page response is valid and positive;
- at least one distribution validates successfully; and
- no human-review trigger in section 12 applies.

**Current:** The collection path enforces the LLM vote and valid-distribution
conditions, but it does not yet enforce all provenance, licensing, sensitivity,
or source-tier requirements.

## 8. Separation of Decision Stages

The system has two different classification paths and they must remain distinct.

### Stage A — repository search relevance

Purpose: determine whether a repository result is useful for the user's search
query.

Current labels are:

- `relevant`;
- `somewhat_relevant`;
- `not_relevant`;
- `insufficient_information`.

`relevant` and `somewhat_relevant` are positive votes for display. This stage
does not independently prove that a result is a global-health dataset, that its
publisher is trusted, or that a distribution works.

**Required policy:** Repository results must be labeled as candidates in the UI
and API. They must pass the collection acceptance gates before being published or
saved as approved catalog records.

### Stage B — collection eligibility

Purpose: decide whether a discovered page is an individual health-relevant
dataset and whether it has a usable distribution.

Current behavior:

1. one DeepSeek model hosted through EPFL RCP classifies the page;
2. a valid structured response is required for a decision;
3. `accepted=true` is required for acceptance;
4. a failed or malformed response causes a classification error;
5. a dataset without a validated distribution is not saved.

This behavior is fail-closed when EPFL RCP cannot produce a valid decision.

## 9. Metadata Quality Requirements

### Required before an approved record is published

- stable dataset URL;
- title;
- publisher or responsible depositor;
- source URL;
- discovery method;
- dataset-classification evidence;
- health-relevance evidence;
- at least one validated distribution;
- validation timestamp and result.

### Strongly recommended

- description;
- publication or update date;
- geography;
- disease or health topic;
- population or demographic information;
- data modality and format;
- dataset size or coverage;
- persistent identifier such as a DOI;
- sharing license or access terms.

Unknown values must not be inferred. Repository metadata currently represents
missing business fields as `"NA"`; persisted dataset fields currently use empty
strings or empty arrays for several missing values. The API should document this
difference until one missing-value convention is adopted.

**Required policy:** License or access terms must be displayed as "unknown" when
not supplied. The catalog must not imply that unknown licensing means open reuse.

**Implementation gap:** `sharing_license`, publication date, disease,
demographics, modality, size, and DOI can be extracted for repository candidates
but are not all persisted on `CollectedDataset`.

## 10. Distribution Policy

### Supported machine-usable formats

The current extractor recognizes:

- CSV, TSV, XLS, and XLSX;
- JSON, JSONL, XML, and GeoJSON;
- Parquet;
- ZIP and GZ archives;
- SAV, DTA, and SAS7BDAT;
- API endpoints.

PDF, HTML, and common image formats are excluded as dataset distributions by
default. They may be retained later as documentation links, but must not satisfy
the usable-distribution gate.

### Validation rules

- Every outbound URL, including distribution URLs and redirect destinations,
  must pass the public-network URL policy before it is fetched.
- Validation should use the least expensive safe request that establishes
  availability.
- A partial `GET` must remain bounded; the current sample limit is 65,536 bytes.
- Redirect destinations and the final content type should be recorded.
- HTML returned for a non-API distribution must fail validation.
- Authentication-required or access-controlled distributions should not be
  described as broken. They should receive an explicit access status once the
  data model supports it.
- A record should expose the time of its most recent validation.

**Current limitation:** Only the first distribution candidate is validated by
default. Consequently, a valid second distribution may be missed when the
highest-ranked candidate fails.

**Current security control:** HTML, JSON, sitemap, and distribution requests use
the shared public-HTTP guard. It validates the initial destination and every
redirect before connecting, and blocks private or local network addresses.

## 11. LLM Governance

### Current decision rule

The default classifiers use one DeepSeek model through EPFL RCP and one API-key
path. There is no
majority vote, provider fallback, or model-level fault isolation.

The successful page voter returns:

- a boolean acceptance decision;
- one `dataset_signals` object whose reason and evidence cover both dataset
  identity and health relevance.

The compatibility audit retains the single vote, failure state, and 1/1
decision threshold.

### Required controls

- Model identifiers and prompt versions must be recorded with evaluation runs.
- A model or prompt change must be evaluated before it becomes the default.
- Page content, metadata, URLs, and query text must be treated as untrusted data.
- LLM output must be schema-validated; malformed output must remain an error.
- No LLM may invent missing publisher, license, geography, or access information.
- Quality evaluation must include both false positives and false negatives.
- Operational model failures must be measured separately from classification
  disagreements.

### Initial evaluation proposal

Before public use, create a reviewed benchmark containing at least:

- clear positive global-health datasets;
- non-health datasets;
- health articles, reports, dashboards, and catalog pages that are not datasets;
- datasets with missing metadata;
- authoritative, repository-hosted, and community-hosted examples;
- broken, redirected, HTML, API, archive, and direct-file distributions;
- multilingual examples representative of target sources.

**Decision required:** Approve benchmark size, languages, acceptable precision
and recall, and the business cost of false positives versus false negatives.

## 12. Human Review

A candidate must be placed in review rather than automatically published when
any of the following is true:

- the source is Tier C or D;
- publisher and hosting platform cannot be distinguished;
- the publisher, license, or provenance is missing or contradictory;
- metadata suggests individual-level health data, credentials, private access,
  or another sensitivity concern;
- the page is a dashboard or report with unclear access to underlying data;
- the final distribution redirects to an unexpected organization or domain;
- a record appears to be a mirror, new edition, or duplicate of an existing one;
- classifier evidence conflicts materially with the structured metadata;
- a previously valid distribution repeatedly fails;
- an exception to this policy is requested.

A review record should contain:

- reviewer identity and date;
- decision: approve, reject, request more information, merge, or withdraw;
- reason and evidence;
- any exception and its expiry date;
- follow-up or revalidation date.

**Implementation gap:** The current schema has no review status, reviewer,
decision reason, or exception record.

## 13. Duplicate, Version, and Mirror Handling

Preferred dataset identity order:

1. persistent identifier and version, such as DOI plus version;
2. authoritative publisher identifier;
3. canonical dataset URL;
4. normalized publisher-title-date fingerprint for review only.

Rules:

- Tracking parameters and fragments should not create a new dataset identity.
- The same dataset found through multiple sources should have one catalog record
  with multiple discovery observations.
- A mirror should point to the primary record where known.
- A materially new version may be represented separately only when users need to
  distinguish it and the version relationship is retained.
- Automatic fuzzy merging must not occur without a reversible audit trail.

**Current:** Database upsert identity is the exact normalized `dataset_url`.
Repeated discoveries can create observations, but DOI-based and cross-URL
duplicate resolution are not implemented.

## 14. Privacy, Ethics, and Licensing

- The catalog should collect only metadata needed for discovery, assessment, and
  audit.
- The collector must not intentionally download complete dataset files during
  validation.
- Metadata indicating direct exposure of names, contact details, patient IDs,
  credentials, or other sensitive person-level information must trigger review.
- Restricted or controlled-access datasets may be cataloged only when their
  access conditions are clear; a login page must not be presented as an open
  distribution.
- License information must be reproduced accurately and linked to its source
  where possible.
- Absence of a license must be shown as unknown, not as permission to reuse.
- The project must not claim that inclusion constitutes ethical, legal, or
  scientific endorsement.

**Decision required:** Obtain legal or data-protection review before the catalog
is exposed publicly or begins indexing sensitive person-level datasets.

## 15. Quality Metrics

The following measures should be reported by release and by source/provider:

| Metric | Definition |
| --- | --- |
| Catalog precision | Percentage of reviewed published records that are genuine health datasets. |
| Dataset recall | Percentage of known eligible benchmark datasets that the pipeline accepts. |
| Repository relevance precision | Percentage of displayed candidates judged relevant or somewhat relevant by human review. |
| Distribution validity rate | Percentage of published records with at least one currently working distribution. |
| Metadata completeness | Percentage of records containing each recommended metadata field. |
| Provenance completeness | Percentage with publisher, source, and discovery method. |
| Duplicate rate | Percentage of reviewed records that duplicate another catalog identity. |
| Review rate | Percentage of candidates requiring human review. |
| Model failure rate | Percentage of voter calls that fail operationally or return invalid output. |
| Classification error rate | Percentage of calls that fail or return invalid structured output. |

Recommended launch criteria, subject to owner approval:

- at least 95% catalog precision on a representative reviewed sample;
- 100% of published records have a dataset URL, title, source, discovery method,
  and at least one recently validated distribution;
- at least 95% provenance completeness;
- no unresolved critical privacy or credential-exposure finding;
- model and prompt versions evaluated against the approved benchmark.

Targets must be recalibrated after the first baseline. A target must never be
reported as achieved without a dated evaluation result and sample size.

## 16. Record Lifecycle

Recommended lifecycle states:

| State | Meaning |
| --- | --- |
| `candidate` | Discovered but not fully evaluated. |
| `pending_review` | Automated checks are insufficient or a review trigger applies. |
| `approved` | All mandatory gates pass or an authorized exception exists. |
| `rejected` | The record is not eligible, with a reason retained. |
| `withdrawn` | Previously approved but removed from publication while retaining an audit trail. |
| `stale` | Revalidation is overdue or all known distributions currently fail. |

Recommended revalidation:

- validate distributions when a dataset is collected;
- revalidate published records on a schedule appropriate to source stability;
- move repeatedly failing records to `stale` or review instead of deleting them
  silently;
- retain first-seen, last-seen, last-checked, and decision timestamps.

**Decision required:** Define revalidation frequency and retention periods for
jobs, observations, rejected candidates, reviews, and withdrawn records.

**Implementation gap:** The current schema persists datasets that passed page
classification and distribution validation, plus job outcomes, but it does not
implement the complete lifecycle above.

## 17. Roles and Accountability

| Role | Responsibility |
| --- | --- |
| Policy owner / product owner | Approves scope, source tiers, acceptance rules, and exceptions. |
| Data steward or reviewer | Reviews uncertain records, duplicates, provenance, licensing, and sensitivity flags. |
| Engineering owner | Implements controls, preserves audit data, and reports implementation gaps. |
| Model/evaluation owner | Maintains the benchmark, evaluates model or prompt changes, and reports quality metrics. |
| Security/privacy reviewer | Reviews public exposure, sensitive metadata, SSRF controls, credentials, and data-protection concerns. |

One person may hold multiple roles during the MVP, but the assigned names and
approval dates should be recorded before public launch.

## 18. Exceptions and Changes

Every exception must record:

- the exact record or source affected;
- the rule being waived;
- the reason and evidence;
- the approving owner;
- the approval and expiry dates;
- any compensating control.

Policy changes must update the document version and change log. Changes to an
acceptance rule should include corresponding tests and, when LLM behavior is
affected, a benchmark evaluation.

## 19. Implementation Gap Register

| Priority | Gap | Recommended change |
| --- | --- | --- |
| P0 | Repository relevance classification does not independently enforce global-health eligibility. | Keep results labeled as candidates and run the page/catalog acceptance gates before save or publication. |
| P0 | No formal handling exists for potentially sensitive person-level metadata or exposed credentials. | Add quarantine/review rules before public use. |
| P1 | Source officiality and trust tiers are not enforced. | Add source type, provenance status, and review requirement. |
| P1 | Review and lifecycle states are absent from the schema. | Add review decision, status, reviewer, reason, and timestamps. |
| P1 | Several useful extracted fields, including sharing license and DOI, are not persisted on collected datasets. | Extend the storage/API contract through an explicit schema migration. |
| P1 | Duplicate identity relies on one normalized dataset URL string. | Add persistent-identifier and cross-URL identity rules. |
| P1 | Only one distribution is validated by default. | Validate additional ranked candidates when the first fails, within a bounded budget. |
| P2 | Missing values differ between repository results and persisted records. | Define one API convention for unknown values while keeping database types appropriate. |
| P2 | Scheduled revalidation, stale status, and withdrawal workflow are absent. | Add periodic link checks and a non-destructive lifecycle. |
| P2 | Model/prompt versions and quality metrics are not stored as first-class evaluation data. | Add an evaluation report and versioned decision metadata. |

## 20. Approval Checklist

Before changing this document from Draft to Approved, confirm:

- [ ] policy owner and technical owner are named;
- [ ] source tiers and the meaning of "official" are approved;
- [ ] mandatory publication metadata is approved;
- [ ] automatic acceptance and human-review triggers are approved;
- [ ] benchmark, precision/recall targets, and languages are approved;
- [ ] duplicate and version rules are approved;
- [ ] privacy and licensing review is complete;
- [ ] revalidation and retention periods are defined;
- [ ] every P0/P1 gap has an owner and target milestone;
- [ ] UI and API language clearly distinguish candidates from approved records.

## 21. Related Documents

- [`../README.md`](../README.md) — setup and current feature overview;
- [`ONBOARDING.md`](ONBOARDING.md) — developer introduction;
- [`technical-design-document.md`](technical-design-document.md) — current
  technical design;
- [`roadmap.md`](roadmap.md) — proposed product and production work;
- [`multi-repository-architecture.md`](multi-repository-architecture.md) —
  proposed multi-provider repository search;
- [`adr/0001-postgresql-only.md`](adr/0001-postgresql-only.md) — PostgreSQL-only
  persistence decision and SQLite history;
- [`classification-architecture.md`](classification-architecture.md) — LLM
  classification contracts and voting behavior;
- [`collector-pipeline-diagram.md`](collector-pipeline-diagram.md) — collector and
  repository-search flows;
- [`database-schema-diagram.md`](database-schema-diagram.md) — current PostgreSQL
  schema.

## 22. Change Log

| Version | Date | Change |
| --- | --- | --- |
| 0.2 | 2026-09-02 | Record shared SSRF protection for distributions and redirects; link split architecture documents. |
| 0.1 | 2026-09-02 | Initial draft based on the current code and project documentation. |
