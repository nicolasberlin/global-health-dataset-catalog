"""Bridge normalized records to the existing classifier and validator contracts."""

from __future__ import annotations

from collector.collection.contracts import StrategyResult
from collector.collection.records import NormalizedRecord
from collector.discovery.adapters.shared import DiscoveredPage


def to_strategy_result(record: NormalizedRecord, method: str) -> StrategyResult:
    return StrategyResult(
        page=DiscoveredPage(
            url=record.landing_url,
            discovery_method=method,
            title=record.title,
            description=record.description,
            publisher=record.publisher,
            date_of_publication=record.publication_date,
            sharing_license=record.license,
            distributions=record.resources,
            doi=record.doi,
            hosting_platform=record.identity.platform,
            record_identity={
                **record.identity.to_dict(),
                **({"parent_persistent_id": record.parent_persistent_id}
                   if record.parent_persistent_id else {}),
            },
            metadata_source_url=record.metadata_source_url,
        ),
        record=record,
        resource_count=len(record.resources),
        discovery_coverage="listed",
        final_url=record.landing_url,
        http_status=200,
    )

