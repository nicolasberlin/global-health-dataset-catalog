# Collection connectors and long-term catalogue architecture

Status: accepted for connector foundation; lifecycle and distributed execution are planned.
Date: 2026-10-12.

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
Keep React/FastAPI, PostgreSQL queues and the isolated optional browser service.
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

## Implemented first delivery

The default registry contains Dataverse and Zenodo. Old Dataverse strategy
entry points remain compatibility wrappers. HTTP and browser metadata pass
through the same selected connector. HTML stays a shared fallback.

Schema migration 13 to 14 adds `collected_datasets.record_identity` as JSONB.
Legacy rows receive an empty object; historical identities are not inferred.
Identity survives local search, API presentation and later HTML-only updates.
Existing URL-based uniqueness and transaction guards remain in effect.

## Subsequent deliveries

1. Extend the catalogue with explicit datasets, versions, resources and external
   references. Define migration and conflict policy before merging identities;
   matching titles alone are insufficient. Keep file and parent identities apart.
2. Add append-only dated observations and versioned policy decisions; separate
   publication state from latest verification state and job state. Add explicit
   revalidation/new-version commands before enabling any recurring collection.
3. Add renewable worker leases, expired-lease recovery and bounded admission for
   multiple processes. PostgreSQL is the initial queue; replacing it requires
   measured capacity or delivery requirements. External calls can repeat after
   crashes, so do not promise exactly-once inference or downloads.
4. Add further connectors and incremental harvesting after contract fixtures and
   representative evaluations. Introduce declarative mappings only where shared
   behavior has been demonstrated.

## Consequences

New record platforms require a connector and registry registration rather than
branches in the collector. Existing classifiers, validator and persistence remain
shared. No automatic cross-repository deduplication or exhaustive harvesting is
claimed by this first delivery. Production still requires one API process/instance
until the queue lease work is implemented and verified.

## References

- [Dataverse native API](https://guides.dataverse.org/en/latest/api/native-api.html)
- [Zenodo records API](https://developers.zenodo.org/#records)
- [Implementation guide](../collection-connectors.md)
