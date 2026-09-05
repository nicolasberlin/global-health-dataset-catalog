# ADR 0001: PostgreSQL-Only Persistence

| Field | Value |
| --- | --- |
| Status | Accepted and implemented |
| Last verified | 2026-09-02 |

## Context

An earlier local version used a SQLite database at
`backend/global_health.db`. The current application requires concurrent backend
access, asynchronous jobs, JSONB fields, transactional job completion, and a
schema contract shared by local and future hosted environments.

## Decision

The runtime uses PostgreSQL only through `DATABASE_URL` and psycopg's async
connection pool.

The application manages its current schema and records the version in
`schema_migrations`. It initializes an empty database, but rejects obsolete,
partial, or hand-modified application schemas rather than guessing migrations.

Historical SQLite data is not imported automatically and there is no SQLite
fallback. If preservation is required, it must be handled as an explicit,
validated import project outside normal startup.

## Consequences

- PostgreSQL is required to run the backend;
- database integration tests require `TEST_DATABASE_URL`;
- collection completion can save all datasets and mark a job done atomically;
- backups and production migration procedures remain deployment concerns;
- old SQLite files and configuration are historical artifacts, not runtime
  documentation.
