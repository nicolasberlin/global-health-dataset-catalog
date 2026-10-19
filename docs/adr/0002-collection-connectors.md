# ADR 0002: Shared collection connectors

Status: accepted and implemented.

## Context

GHDC searches locally before querying DataCite, classifies external candidates,
and collects accepted references with shared page classification and resource
validation. Dataverse resolution was embedded in both the orchestrator and the
browser client. Adding another platform would repeat those dependencies.

Existing queues, vote checkpoints, network protections, bounded validation and
atomic finalization must remain authoritative. A repository candidate is not a
validated dataset; a file record must not expand into its parent dataset.

## Decision

Use a modular monolith with explicit collection ports and platform adapters.
Keep FastAPI, PostgreSQL queues and the isolated optional browser service.
Do not introduce a separate service per platform.

- `RecordConnector` recognizes a record URL, validates and normalizes its API
  response, and limits fallback resources to the requested record scope.
- `ConnectorRegistry` selects configured connectors without network requests.
  Hosts are trusted server configuration, not payload data.
- `NormalizedRecord` is an observation before acceptance. It has a scoped
  `RecordIdentity`, metadata source, resource candidates and optional parent PID.
- Compatibility conversion feeds existing `DiscoveredPage`, `PageSnapshot`
  and `DistributionCandidate` contracts. The fixed display/classification
  metadata mapping is not the catalogue's identity model.
- The shared pipeline prepares classifier evidence. The orchestrator owns
  fallback decisions, resource limits, deadlines and diagnostics. Connectors
  cannot classify, approve, save datasets or create unbounded retries.
- Backend workers retain responsibility for checkpointing and atomic
  finalization. Domain modules do not import backend database code.

Search providers, record resolvers and future catalogue harvesters have separate
interfaces. A platform can implement any of these capabilities without being
required to implement all of them.

## Implemented scope

The default registry contains Dataverse, Zenodo, Figshare, Dryad, InvenioRDM
and DSpace. HTTP and browser metadata pass through the same selected connector;
HTML stays a shared fallback. Platform recognition and enabled hosts are defined
in `collector/collection/registry.py` and `collector/config.py`.

The initial schema includes `collected_datasets.record_identity` as JSONB.
Its default is an empty object; missing identities are not inferred.
Identity survives local search, API presentation and later HTML-only updates.
Existing URL-based uniqueness and transaction guards remain in effect.

## Consequences

New record platforms require a connector and registry registration rather than
branches in the collector. Existing classifiers, validator and persistence remain
shared. No automatic cross-repository deduplication or exhaustive harvesting is
provided. Run one API process and instance per database schema; the current
ownership fence does not provide distributed queue leases. Future work belongs
in the [maintainer backlog](../../TODO.txt), rather than this accepted decision.

## References

- [Dataverse native API](https://guides.dataverse.org/en/latest/api/native-api.html)
- [Zenodo records API](https://developers.zenodo.org/#records)
- [Implementation guide](../reference/collection-connectors.md)
