# Product and Production Roadmap

> Status: proposed work, not current architecture. Last reviewed 2026-09-11.

This document keeps future work separate from the current
[Technical Design Document](technical-design-document.md). Items are ordered by
risk and dependency, not by a committed delivery date.

## 1. Collection Quality Gates

- connect repository candidates to the collection pipeline instead of treating
  relevance as publication approval;
- enforce health relevance, dataset identity, provenance, usable distribution,
  source tier, licence, and sensitivity gates from the
  the planned dataset collection and quality policy;
- store review status, reviewer decisions, policy exceptions, and decision
  timestamps;
- distinguish candidate, accepted, published, stale, and withdrawn records.

## 2. Identity and Lifecycle

- persist DOI and other stable identifiers as first-class fields;
- detect duplicates by identifier and semantic identity, not only one normalized URL string;
- model versions, mirrors, replacements, and withdrawals explicitly;
- schedule link revalidation and expose stale/broken status without deleting
  historical observations.

## 3. Repository Coverage

Detailed design: [Multi-Repository Architecture](props/multi-repository-architecture.md).

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
- decide whether provider-level independence or fallback models are required;
  the current three-model ensemble still depends on one EPFL RCP endpoint.

## 5. Production Architecture

- replace static MVP tokens with institutional authentication and role-based
  authorization;
- extend the PostgreSQL collection queue with worker leases and multi-instance
  recovery, and persist classification work independently of HTTP requests;
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
