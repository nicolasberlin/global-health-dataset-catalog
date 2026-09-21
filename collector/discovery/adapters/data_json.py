"""data.json catalog discovery adapter and metadata helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collector.discovery.adapters.shared import (
    EXCLUDED_RESOURCE_FORMATS,
    DiscoveredPage,
    JsonFetcher,
    _dedupe,
    _demographics_from_mapping,
    _diseases_from_mapping,
    _first_mapping_value,
    _first_text,
    _first_text_value,
    _first_url,
    _geography_from_mapping,
    _json_ld_type_matches,
    _mapping_dicts,
    _modalities_from_distributions,
    _modalities_from_format,
    _normalize_format,
    _publication_date_from_mapping,
    _site_root,
    _text,
    _text_values,
    _value_text,
    fetch_json_url,
)
from collector.extraction.distributions import guess_format
from collector.storage.models import DistributionCandidate
from collector.url_utils import canonicalize_url


class DataJsonAdapter:
    """Detect and discover datasets from a source's data.json catalog."""

    name = "data_json"

    def __init__(
        self,
        fetch_json: JsonFetcher | None = None,
        rows: int = 5,
    ) -> None:
        self._fetch_json = fetch_json or fetch_json_url
        self._rows = rows

    def detect(self, source_url: str) -> bool:
        try:
            data = self._fetch_json(_data_json_url(source_url))
        except ValueError:
            return False

        return bool(_data_json_datasets(data))

    def discover(self, source_url: str) -> list[DiscoveredPage]:
        data_json_url = _data_json_url(source_url)
        data = self._fetch_json(data_json_url)
        query = _source_query(source_url)
        discovered_pages: list[DiscoveredPage] = []

        for dataset in _data_json_datasets(data):
            if query and not _data_json_dataset_matches_query(dataset, query):
                continue

            dataset_url = _data_json_dataset_url(source_url, data_json_url, dataset)
            if not dataset_url:
                continue

            distributions = tuple(_data_json_distribution_candidates(source_url, dataset))
            discovered_pages.append(
                DiscoveredPage(
                    url=dataset_url,
                    discovery_method=self.name,
                    priority=0.9 if distributions else 0.75,
                    title=_first_text(dataset, "title", "dct:title", "name"),
                    description=_first_text(dataset, "description", "dct:description"),
                    publisher=_data_json_publisher(dataset),
                    geography=tuple(_geography_from_mapping(dataset)),
                    date_of_publication=_publication_date_from_mapping(dataset),
                    diseases=_diseases_from_mapping(dataset),
                    size_of_dataset=_size_from_data_json_dataset(dataset),
                    demographic_information=_demographics_from_mapping(dataset),
                    sharing_license=_first_mapping_value(
                        dataset,
                        "license",
                        "dct:license",
                        "rights",
                        "dct:rights",
                    ),
                    modality_of_data=_modalities_from_data_json_dataset(
                        dataset,
                        distributions,
                    ),
                    distributions=distributions,
                    discovery_metadata={
                        "data_json_url": data_json_url,
                        "identifier": _first_text(dataset, "identifier", "@id"),
                        "keywords": _text_values(dataset.get("keyword")),
                    },
                )
            )

            if len(discovered_pages) >= self._rows:
                break

        return discovered_pages


def _data_json_url(source_url: str) -> str:
    parts = urlsplit(source_url)
    if parts.path.rstrip("/").endswith("/data.json") or parts.path == "/data.json":
        return canonicalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))

    return canonicalize_url("data.json", _site_root(source_url))


def _data_json_datasets(data: dict[str, object]) -> list[dict[object, object]]:
    datasets = data.get("dataset")
    if isinstance(datasets, list):
        return [dataset for dataset in datasets if isinstance(dataset, dict)]

    graph = data.get("@graph")
    if isinstance(graph, list):
        return [
            item
            for item in graph
            if isinstance(item, dict) and _json_ld_type_matches(item.get("@type"), "Dataset")
        ]

    return []


def _data_json_dataset_url(
    source_url: str,
    data_json_url: str,
    dataset: dict[object, object],
) -> str:
    for key in ("landingPage", "dcat:landingPage", "accessURL", "dcat:accessURL", "@id"):
        value = _first_url(dataset.get(key))
        if value:
            return canonicalize_url(value, _site_root(source_url))

    identifier = _first_text(dataset, "identifier")
    if identifier:
        return f"{data_json_url}?{urlencode({'identifier': identifier})}"

    return data_json_url


def _data_json_distribution_candidates(
    source_url: str,
    dataset: dict[object, object],
) -> list[DistributionCandidate]:
    distributions = dataset.get("distribution") or dataset.get("dcat:distribution")
    if isinstance(distributions, dict):
        distribution_items = [distributions]
    elif isinstance(distributions, list):
        distribution_items = [
            distribution
            for distribution in distributions
            if isinstance(distribution, dict)
        ]
    else:
        distribution_items = []

    candidates: list[DistributionCandidate] = []
    for distribution in distribution_items:
        download_url = _first_url(
            distribution.get("downloadURL"),
            distribution.get("dcat:downloadURL"),
        )
        access_url = _first_url(
            distribution.get("accessURL"),
            distribution.get("dcat:accessURL"),
        )
        resource_url = download_url or access_url
        if not resource_url:
            continue

        title = _first_text(distribution, "title", "dct:title", "name")
        description = _first_text(distribution, "description", "dct:description")
        media_type = _first_text(distribution, "mediaType", "dcat:mediaType")
        format_text = _first_text(distribution, "format", "dct:format")
        effective_mime_type = media_type or (format_text if "/" in format_text else "")
        anchor = title or description
        format_name, extension = _data_json_format(
            resource_url,
            format_text,
            effective_mime_type,
            anchor,
            has_download_url=bool(download_url),
        )

        if format_name in EXCLUDED_RESOURCE_FORMATS:
            continue

        candidates.append(
            DistributionCandidate(
                url=canonicalize_url(resource_url, source_url),
                format=format_name,
                probability=0.95 if download_url else 0.75,
                anchor=anchor,
                extension=extension,
                mime_type=effective_mime_type,
                same_domain=urlsplit(resource_url).netloc.lower()
                == urlsplit(source_url).netloc.lower(),
                signals={
                    "data_json_distribution": True,
                    "download_url": bool(download_url),
                    "access_url": bool(access_url),
                },
            )
        )

    return candidates


def _data_json_format(
    resource_url: str,
    format_text: str,
    media_type: str,
    anchor: str,
    has_download_url: bool,
) -> tuple[str, str]:
    guessed_format, extension = guess_format(resource_url, anchor=anchor, mime_type=media_type)
    if format_text and "/" not in format_text:
        normalized_format = _normalize_format(format_text)
        if normalized_format and normalized_format not in {"DATA", "FILE"}:
            return normalized_format, extension

    if guessed_format != "UNKNOWN":
        return guessed_format, extension

    return ("UNKNOWN" if has_download_url else "API"), extension


def _data_json_publisher(dataset: dict[object, object]) -> str:
    publisher = dataset.get("publisher") or dataset.get("dct:publisher")
    if isinstance(publisher, dict):
        return _first_text(publisher, "name", "title", "foaf:name", "dct:title")

    return _first_text_value(publisher)


def _size_from_data_json_dataset(dataset: dict[object, object]) -> str:
    direct_size = _first_mapping_value(
        dataset,
        "size",
        "contentSize",
        "content_size",
        "dcat:byteSize",
        "byteSize",
    )
    if direct_size:
        return direct_size

    sizes: list[str] = []
    for distribution in _data_json_distribution_items(dataset):
        for key in ("byteSize", "dcat:byteSize", "contentSize", "size"):
            value = _value_text(distribution.get(key))
            if value:
                sizes.append(value)
    return ", ".join(_dedupe(sizes))


def _data_json_distribution_items(dataset: dict[object, object]) -> list[dict[object, object]]:
    return _mapping_dicts(dataset.get("distribution") or dataset.get("dcat:distribution"))


def _modalities_from_data_json_dataset(
    dataset: dict[object, object],
    distributions: tuple[DistributionCandidate, ...],
) -> tuple[str, ...]:
    values = list(_modalities_from_distributions(distributions))
    for distribution in _data_json_distribution_items(dataset):
        for key in ("format", "dct:format", "mediaType", "dcat:mediaType"):
            for format_value in _text_values(distribution.get(key)):
                values.extend(_modalities_from_format(format_value))
    return tuple(_dedupe(values))


def _data_json_dataset_matches_query(dataset: dict[object, object], query: str) -> bool:
    searchable_text = " ".join(
        [
            _first_text(dataset, "title", "dct:title", "name"),
            _first_text(dataset, "description", "dct:description"),
            _data_json_publisher(dataset),
            " ".join(_text_values(dataset.get("keyword"))),
            " ".join(_text_values(dataset.get("theme"))),
        ]
    ).lower()
    return query.lower() in searchable_text


def _source_query(source_url: str) -> str:
    return _text(dict(parse_qsl(urlsplit(source_url).query)).get("q"))
