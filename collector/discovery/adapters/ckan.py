from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from collector.discovery.adapters.shared import (
    EXCLUDED_RESOURCE_FORMATS,
    DiscoveredPage,
    JsonFetcher,
    _demographics_from_mapping,
    _diseases_from_mapping,
    _first_mapping_value,
    _geography_from_mapping,
    _mapping_dicts,
    _modalities_from_distributions,
    _normalize_format,
    _publication_date_from_mapping,
    _text,
    _value_text,
    fetch_json_url,
)
from collector.extraction.distributions import guess_format
from collector.storage.models import DistributionCandidate
from collector.url_utils import canonicalize_url


class CKANAdapter:
    name = "ckan"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        rows: int = 5,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._rows = rows

    def detect(self, source_url: str) -> bool:
        try:
            data = self._fetch_json(_ckan_action_url(source_url, "status_show"))
        except ValueError:
            return False

        return data.get("success") is True and isinstance(data.get("result"), dict)

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        data = self._fetch_json(
            _ckan_action_url(
                source_url,
                "package_search",
                _ckan_search_params(source_url, self._rows),
            )
        )
        result = data.get("result")
        if data.get("success") is not True or not isinstance(result, dict):
            return []

        packages = result.get("results")
        if not isinstance(packages, list):
            return []

        discovered_pages: list[DiscoveredPage] = []
        for package in packages:
            if not isinstance(package, dict):
                continue

            dataset_url = _dataset_page_url(source_url, package)
            if not dataset_url:
                continue

            distributions = tuple(_distribution_candidates(source_url, package))
            discovered_pages.append(
                DiscoveredPage(
                    url=dataset_url,
                    discovery_method=self.name,
                    priority=0.9 if distributions else 0.75,
                    title=_text(package.get("title")),
                    description=_text(package.get("notes")),
                    publisher=_publisher(package),
                    geography=tuple(_geography_from_mapping(package)),
                    date_of_publication=_publication_date_from_mapping(package),
                    diseases=_diseases_from_mapping(package),
                    size_of_dataset=_size_from_ckan_package(package),
                    demographic_information=_demographics_from_mapping(package),
                    sharing_license=_first_mapping_value(
                        package,
                        "license_title",
                        "license_id",
                        "license_url",
                        "license",
                        "rights",
                    ),
                    modality_of_data=_modalities_from_distributions(distributions),
                    distributions=distributions,
                    discovery_metadata={
                        "ckan_id": _text(package.get("id")),
                        "ckan_name": _text(package.get("name")),
                    },
                )
            )

        return discovered_pages


def _ckan_action_url(
    source_url: str,
    action: str,
    params: dict[str, str] | None = None,
) -> str:
    base_url = _ckan_site_root(source_url)
    action_url = urljoin(base_url, f"api/3/action/{action}")
    if not params:
        return action_url

    return f"{action_url}?{urlencode(params)}"


def _ckan_site_root(source_url: str) -> str:
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _ckan_search_params(source_url: str, rows: int) -> dict[str, str]:
    supported_params = {"q", "fq", "sort"}
    source_params = dict(parse_qsl(urlsplit(source_url).query))
    params = {
        key: value
        for key, value in source_params.items()
        if key in supported_params and value.strip()
    }
    params["rows"] = str(rows)
    return params


def _dataset_page_url(source_url: str, package: dict[object, object]) -> str:
    name = _text(package.get("name"))
    if name:
        return canonicalize_url(f"dataset/{name}", _ckan_site_root(source_url))

    package_id = _text(package.get("id"))
    if package_id:
        return canonicalize_url(f"dataset/{package_id}", _ckan_site_root(source_url))

    return ""


def _distribution_candidates(
    source_url: str,
    package: dict[object, object],
) -> list[DistributionCandidate]:
    resources = package.get("resources")
    if not isinstance(resources, list):
        return []

    distributions: list[DistributionCandidate] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue

        resource_url = _text(resource.get("url"))
        if not resource_url:
            continue

        resource_format = _normalize_format(_text(resource.get("format")))
        mime_type = _text(resource.get("mimetype")) or _text(resource.get("mimetype_inner"))
        anchor = _text(resource.get("name")) or _text(resource.get("description"))
        guessed_format, extension = guess_format(resource_url, anchor=anchor, mime_type=mime_type)
        format_name = resource_format or guessed_format

        if format_name in EXCLUDED_RESOURCE_FORMATS:
            continue

        distributions.append(
            DistributionCandidate(
                url=canonicalize_url(resource_url, source_url),
                format=format_name,
                probability=0.95,
                anchor=anchor,
                extension=extension,
                mime_type=mime_type,
                same_domain=False,
                signals={"ckan_resource": True},
            )
        )

    return distributions


def _publisher(package: dict[object, object]) -> str:
    organization = package.get("organization")
    if not isinstance(organization, dict):
        return ""

    return _text(organization.get("title")) or _text(organization.get("name"))


def _size_from_ckan_package(package: dict[object, object]) -> str:
    direct_size = _first_mapping_value(
        package,
        "size",
        "content_size",
        "dataset_size",
        "record_count",
    )
    if direct_size:
        return direct_size

    sizes = [
        _value_text(resource.get("size"))
        for resource in _mapping_dicts(package.get("resources"))
        if _value_text(resource.get("size"))
    ]
    return ", ".join(dict.fromkeys(sizes))
