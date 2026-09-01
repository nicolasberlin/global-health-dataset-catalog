# Database Schema Diagram

This document is a compact visual reference for the PostgreSQL schema managed by
the application.

The PostgreSQL database is managed by the application. A new database starts at
the current application schema, recorded in `schema_migrations`.

```mermaid
erDiagram
    schema_migrations {
        int version PK
        timestamptz applied_at
    }

    data_sources {
        int id PK
        string source_key UK
        string name
        string description
        string theme
        string page_url
    }

    collection_jobs {
        int id PK
        string source_url
        string status
        int saved_count
        int discovered_count
        int analyzed_count
        int accepted_count
        int rejected_count
        int invalid_distribution_count
        jsonb discovery_methods
        string message
        string error
        timestamptz created_at
        timestamptz updated_at
        timestamptz finished_at
    }

    collected_datasets {
        int id PK
        string source_url
        string dataset_url UK
        string title
        string description
        string publisher
        string hosting_platform
        string uploader
        jsonb geography
        string discovery_method
        jsonb dataset_signals
        jsonb health_signals
        timestamptz first_seen_at
        timestamptz last_seen_at
        timestamptz created_at
        timestamptz updated_at
    }

    collected_distributions {
        int id PK
        int dataset_id FK
        string url
        string format
        float probability
        string anchor
        string extension
        string mime_type
        string nearby_text
        bool same_domain
        string dom_path
        jsonb signals
        timestamptz first_seen_at
        timestamptz last_seen_at
        timestamptz last_checked_at
        bool validation_attempted
        string validation_final_url
        bool validation_ok
        int validation_http_status
        string validation_mime_type
        int validation_size_bytes
        string validation_etag
        string validation_last_modified
        string validation_content_disposition
        string validation_error
    }

    dataset_discovery_observations {
        int id PK
        int collection_job_id FK
        int dataset_id FK
        string source_url
        string discovery_method
        timestamptz observed_at
    }

    collected_datasets ||--o{ collected_distributions : "delete cascade"
    collected_datasets ||--o{ dataset_discovery_observations : "delete cascade"
    collection_jobs ||--o{ dataset_discovery_observations : "set null"
```
