# ADR 0001: PostgreSQL-Only Persistence

Status: accepted and implemented.

## Context

Background jobs, JSONB metadata and atomic catalogue updates require a shared
transactional database. Local development and hosted deployments must use the
same persistence contract.

## Decision

The runtime uses PostgreSQL only through `DATABASE_URL` and psycopg's async
connection pool.

The application manages its current schema and records the version in
`schema_migrations`. One initial migration creates the complete version 1 schema
in an empty database. Version 2 restricts search access modes to local/public
without rewriting existing identities or result records. Earlier pre-release
databases outside this migration history are not converted automatically.
Unsupported, partial or hand-modified schemas are rejected rather than repaired
by guessing. Current operations are documented in
[schema migration and validation](../DEPLOYMENT.md#schema-validation-and-retired-source-administration).

There is no SQLite runtime or automatic import of historical SQLite data.

## Consequences

- PostgreSQL is required to run the backend;
- database integration tests require `TEST_DATABASE_URL`;
- collection completion can save all datasets and mark a job done atomically;
- backups and production migration procedures remain deployment concerns.
