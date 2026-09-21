"""Socrata catalog discovery adapter and metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collector.discovery.adapters.shared import (
    DiscoveredPage,
    JsonFetcher,
    _dedupe,
    _demographics_from_mapping,
    _diseases_from_mapping,
    _first_mapping_value,
    _geography_from_mapping,
    _modalities_from_distributions,
    _publication_date_from_mapping,
    _text,
    fetch_json_url,
)
from collector.storage.models import DistributionCandidate
from collector.url_utils import canonicalize_url


@dataclass(frozen=True)
class SocrataCatalogResult:
    """Socrata resource and metadata sections used to build one result."""

    resource: dict[object, object]
    metadata: dict[object, object]
    permalink: str = ""
    link: str = ""


class SocrataAdapter:
    """Detect Socrata portals and discover datasets through its catalog API."""

    name = "socrata"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        rows: int = 5,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._rows = rows

    def detect(self, source_url: str) -> bool:
        try:
            data = self._fetch_json(
                _socrata_catalog_url(source_url, rows=1, include_source_query=False)
            )
        except ValueError:
            return False

        return bool(_socrata_results(data, source_url))

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        data = self._fetch_json(
            _socrata_catalog_url(source_url, rows=self._rows, include_source_query=True)
        )

        discovered_pages: list[DiscoveredPage] = []
        for result in _socrata_results(data, source_url):
            resource = result.resource
            socrata_id = _text(resource.get("id"))
            if not socrata_id:
                continue

            dataset_url = _socrata_dataset_url(source_url, result)
            if not dataset_url:
                continue

            distributions = tuple(_socrata_distribution_candidates(source_url, socrata_id))
            discovered_pages.append(
                DiscoveredPage(
                    url=dataset_url,
                    discovery_method=self.name,
                    priority=0.9,
                    title=_text(resource.get("name")),
                    description=_text(resource.get("description")),
                    publisher=_text(resource.get("attribution")),
                    geography=tuple(
                        _dedupe(
                            [
                                *_geography_from_mapping(resource),
                                *_geography_from_mapping(result.metadata),
                            ]
                        )
                    ),
                    date_of_publication=(
                        _publication_date_from_mapping(resource)
                        or _publication_date_from_mapping(result.metadata)
                    ),
                    diseases=_diseases_from_mapping(resource, result.metadata),
                    size_of_dataset=(
                        _first_mapping_value(resource, "size", "content_size", "rows")
                        or _first_mapping_value(result.metadata, "size", "content_size", "rows")
                    ),
                    demographic_information=_demographics_from_mapping(
                        resource,
                        result.metadata,
                    ),
                    sharing_license=(
                        _first_mapping_value(
                            resource,
                            "license_title",
                            "license",
                            "license_id",
                            "license_url",
                            "rights",
                        )
                        or _first_mapping_value(
                            result.metadata,
                            "license_title",
                            "license",
                            "license_id",
                            "license_url",
                            "rights",
                        )
                    ),
                    modality_of_data=_modalities_from_distributions(distributions),
                    distributions=distributions,
                    discovery_metadata={
                        "socrata_id": socrata_id,
                        "socrata_type": _text(resource.get("type")),
                        "socrata_domain": _socrata_domain(source_url),
                    },
                )
            )

        return discovered_pages


def _socrata_catalog_url(
    source_url: str,
    rows: int,
    include_source_query: bool,
) -> str:
    domain = _socrata_domain(source_url)
    params = {
        "domains": domain,
        "search_context": domain,
        "limit": str(rows),
    }
    if include_source_query:
        source_params = dict(parse_qsl(urlsplit(source_url).query))
        query = _text(source_params.get("q"))
        if query:
            params["q"] = query

    return f"https://api.us.socrata.com/api/catalog/v1?{urlencode(params)}"


def _socrata_domain(source_url: str) -> str:
    return urlsplit(source_url).netloc.lower()


def _socrata_results(
    data: dict[str, object],
    source_url: str,
) -> list[SocrataCatalogResult]:
    results = data.get("results")
    if not isinstance(results, list):
        return []

    source_domain = _socrata_domain(source_url)
    socrata_results: list[SocrataCatalogResult] = []
    for result in results:
        if not isinstance(result, dict):
            continue

        resource = result.get("resource")
        if not isinstance(resource, dict):
            continue

        metadata = result.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        result_domain = _text(metadata.get("domain")) or _text(resource.get("domain"))
        if result_domain and result_domain.lower() != source_domain:
            continue

        resource_type = _text(resource.get("type")).lower()
        if resource_type and resource_type not in {"dataset", "file"}:
            continue

        socrata_results.append(
            SocrataCatalogResult(
                resource=resource,
                metadata=metadata,
                permalink=_text(result.get("permalink")),
                link=_text(result.get("link")),
            )
        )

    return socrata_results


def _socrata_dataset_url(
    source_url: str,
    result: SocrataCatalogResult,
) -> str:
    if result.permalink:
        return canonicalize_url(result.permalink, _socrata_site_root(source_url))
    if result.link:
        return canonicalize_url(result.link, _socrata_site_root(source_url))

    resource = result.resource
    metadata = result.metadata
    for key in ("permalink", "link", "webUri", "web_uri"):
        resource_url = _text(resource.get(key)) or _text(metadata.get(key))
        if resource_url:
            return canonicalize_url(resource_url, _socrata_site_root(source_url))

    socrata_id = _text(resource.get("id"))
    if not socrata_id:
        return ""

    return canonicalize_url(f"d/{socrata_id}", _socrata_site_root(source_url))


def _socrata_distribution_candidates(
    source_url: str,
    socrata_id: str,
) -> list[DistributionCandidate]:
    site_root = _socrata_site_root(source_url)
    csv_url = canonicalize_url(f"resource/{socrata_id}.csv", site_root)
    json_url = canonicalize_url(f"resource/{socrata_id}.json", site_root)
    api_url = canonicalize_url(
        f"resource/{socrata_id}.json?{urlencode({'$limit': '1'})}",
        site_root,
    )

    return [
        DistributionCandidate(
            url=csv_url,
            format="CSV",
            probability=0.95,
            anchor="Socrata CSV export",
            extension=".csv",
            mime_type="text/csv",
            same_domain=True,
            signals={"socrata_resource": True},
        ),
        DistributionCandidate(
            url=json_url,
            format="JSON",
            probability=0.9,
            anchor="Socrata JSON export",
            extension=".json",
            mime_type="application/json",
            same_domain=True,
            signals={"socrata_resource": True},
        ),
        DistributionCandidate(
            url=api_url,
            format="API",
            probability=0.85,
            anchor="Socrata SODA API",
            extension=".json",
            mime_type="application/json",
            same_domain=True,
            signals={"socrata_resource": True, "api_endpoint": True},
        ),
    ]


def _socrata_site_root(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
