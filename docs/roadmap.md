# Product and Production Roadmap

> Status: proposed work, not current architecture. Last reviewed 2026-09-02.

This document keeps future work separate from the current
[Technical Design Document](technical-design-document.md). Items are ordered by
risk and dependency, not by a committed delivery date.

## 1. Collection Quality Gates

- connect repository candidates to the collection pipeline instead of treating
  relevance as publication approval;
- enforce health relevance, dataset identity, provenance, usable distribution,
  source tier, licence, and sensitivity gates from the
  [Dataset Collection & Quality Policy](dataset-collection-and-quality-policy.md);
- store review status, reviewer decisions, policy exceptions, and decision
  timestamps;
- distinguish candidate, accepted, published, stale, and withdrawn records.

## 2. Identity and Lifecycle

- persist DOI and other stable identifiers as first-class fields;
- detect duplicates by identifier and normalized identity, not only exact URL;
- model versions, mirrors, replacements, and withdrawals explicitly;
- schedule link revalidation and expose stale/broken status without deleting
  historical observations.

## 3. Repository Coverage

Detailed design: [Multi-Repository Architecture](multi-repository-architecture.md).

- add providers only through `repository_search/providers/`;
- define provider timeouts, quotas, and normalized provenance requirements;
- retain partial-provider warnings and fail only when no provider succeeds;
- evaluate DataCite, Dataverse, CKAN, and other repository APIs against a shared
  benchmark before enabling them by default.

## 4. LLM Governance

- version prompts and model configuration with stored decisions;
- create a labeled evaluation set and measure precision, recall, disagreement,
  failure rates, latency, and cost;
- add a human-review path for uncertainty and policy triggers;
- decide whether provider-level independence is required instead of relying on
  three models behind one OpenAI provider.

## 5. Production Architecture

- add authentication and role-based authorization;
- replace process-local FastAPI background tasks with a durable queue and worker;
- define retries, idempotency, cancellation, and dead-letter handling;
- deploy PostgreSQL with backups, migrations, pooling, and least-privilege roles;
- move secrets into environment-specific secret management;
- add centralized logs, metrics, traces, dashboards, and alerts;
- run ruff, frontend build, all Python tests, and PostgreSQL integration tests in
  CI before deployment;
- define staging and production release/rollback procedures.

## 6. Open Decisions

- policy owner and technical owner;
- approved meaning of "official";
- source trust tiers and exception authority;
- acceptable licences and access restrictions;
- privacy/sensitivity review rules;
- target repository providers and languages;
- production hosting, queue, monitoring, and backup platforms.
