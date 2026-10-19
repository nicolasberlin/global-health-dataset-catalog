from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from collector.diagnostics import Diagnostic, PipelineFailure
from collector.execution import ExecutionStopped
from collector.extraction.dataset_metadata import DATASET_METADATA_KEYS
from collector.extraction.errors import ExtractionError
from collector.repository_search import (
    INVALID_METADATA_MESSAGE,
    PROVIDER_UNAVAILABLE_MESSAGE,
    DataCiteRepositorySearchProvider,
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.repository_search.providers import datacite


def test_datacite_provider_builds_query_url_and_normalizes_results():
    requested_urls = []

    def fake_fetch_json(url):
        requested_urls.append(url)
        return {
            "data": [
                {
                    "id": "10.1234/malaria",
                    "attributes": {
                        "doi": "10.1234/malaria",
                        "titles": [{"title": "Malaria mortality estimates"}],
                        "descriptions": [
                            {
                                "description": (
                                    "<p>Annual mortality estimates by age and sex.</p>"
                                ),
                                "descriptionType": "Abstract",
                            }
                        ],
                        "url": "https://example.org/datasets/malaria-mortality",
                        "publisher": {"name": "Global Health Repository"},
                        "publicationYear": 2025,
                        "geoLocations": [
                            {
                                "geoLocationPlace": "Burkina Faso",
                                "geoLocationCountry": "BF",
                            }
                        ],
                        "subjects": [
                            {"subject": "malaria"},
                            {"subject": "mortality"},
                        ],
                        "sizes": ["12,000 records"],
                        "rightsList": [
                            {
                                "rights": "Creative Commons Attribution 4.0",
                                "rightsIdentifier": "CC-BY-4.0",
                            }
                        ],
                        "formats": ["CSV"],
                        "types": {
                            "resourceTypeGeneral": "Dataset",
                            "resourceType": "Epidemiological dataset",
                        },
                    },
                }
            ]
        }

    results = DataCiteRepositorySearchProvider(
        fetch_json=fake_fetch_json,
        page_size=3,
    ).search("malaria mortality").results

    assert len(requested_urls) == 1
    request = urlsplit(requested_urls[0])
    assert request.scheme == "https"
    assert request.netloc == "api.datacite.org"
    assert request.path == "/dois"
    assert parse_qs(request.query) == {
        "query": ["malaria mortality"],
        "resource-type-id": ["dataset"],
        "page[size]": ["3"],
        "sort": ["relevance"],
    }

    assert len(results) == 1
    result = results[0]
    assert result.title == "Malaria mortality estimates"
    assert result.description == "Annual mortality estimates by age and sex."
    assert result.url == "https://example.org/datasets/malaria-mortality"
    assert result.source == "DataCite"
    assert result.publisher == "Global Health Repository"
    assert result.date == "2025"
    assert result.doi == "10.1234/malaria"
    assert result.keywords == ["malaria", "mortality"]
    assert tuple(result.metadata) == DATASET_METADATA_KEYS
    assert result.metadata == {
        "Title": "Malaria mortality estimates",
        "Geography": "Burkina Faso, BF",
        "Date of publication": "2025",
        "Dataset URL": "https://example.org/datasets/malaria-mortality",
        "Disease(s)": "malaria",
        "Size of dataset": "12,000 records",
        "Demographic information": "age, sex",
        "Sharing license": "Creative Commons Attribution 4.0, CC-BY-4.0",
        "Modality of data": "tabular",
        "Description of dataset": "Annual mortality estimates by age and sex.",
    }


def test_datacite_provider_uses_na_for_missing_search_result_metadata():
    def fake_fetch_json(url):
        return {
            "data": [
                {
                    "id": "10.1234/minimal",
                    "attributes": {
                        "doi": "10.1234/minimal",
                    },
                }
            ]
        }

    response = DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search(
        "minimal"
    )
    results = response.results
    assert response.warnings == []

    assert len(results) == 1
    assert tuple(results[0].metadata) == DATASET_METADATA_KEYS
    assert results[0].metadata == {
        "Title": "NA",
        "Geography": "NA",
        "Date of publication": "NA",
        "Dataset URL": "https://doi.org/10.1234/minimal",
        "Disease(s)": "NA",
        "Size of dataset": "NA",
        "Demographic information": "NA",
        "Sharing license": "NA",
        "Modality of data": "NA",
        "Description of dataset": "NA",
    }


def test_datacite_provider_uses_doi_resolver_when_landing_url_is_missing():
    def fake_fetch_json(url):
        return {
            "data": [
                {
                    "id": "https://doi.org/10.1234/missing-url",
                    "attributes": {
                        "titles": [{"title": "Dataset without URL"}],
                        "publisher": "Repository Publisher",
                        "dates": [{"date": "2024-06-30", "dateType": "Issued"}],
                    },
                }
            ]
        }

    response = DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search(
        "missing url"
    )
    results = response.results
    assert response.warnings == []

    assert len(results) == 1
    assert results[0].url == "https://doi.org/10.1234/missing-url"
    assert results[0].doi == "10.1234/missing-url"
    assert results[0].publisher == "Repository Publisher"
    assert results[0].date == "2024-06-30"


def test_datacite_provider_uses_doi_resolver_when_landing_url_is_invalid():
    def fake_fetch_json(url):
        return {
            "data": [
                {
                    "id": "10.1234/invalid-url",
                    "attributes": {
                        "titles": [{"title": "Dataset with invalid URL"}],
                        "url": "/relative-dataset-url",
                    },
                },
                {
                    "attributes": {
                        "titles": [{"title": "Dataset without usable URL"}],
                        "url": "javascript:alert(1)",
                    },
                },
            ]
        }

    response = DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search(
        "invalid url"
    )
    results = response.results

    assert len(results) == 1
    assert results[0].url == "https://doi.org/10.1234/invalid-url"
    assert len(response.warnings) == 1
    assert response.warnings[0].code == "invalid_repository_metadata"
    assert response.warnings[0].provider == "DataCite"


def test_datacite_provider_fails_clearly_for_invalid_top_level_response():
    def fake_fetch_json(url):
        return {"errors": [{"title": "bad request"}]}

    try:
        DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search("malaria")
    except ValueError as exception:
        assert str(exception) == "Invalid DataCite response shape: expected data list."
    else:
        raise AssertionError("Expected ValueError.")


def test_search_repository_metadata_preserves_provider_result_order():
    class FakeProvider:
        name = "fake"

        def search(self, query):
            assert query == "malaria mortality"
            return RepositorySearchResponse(results=[
                RepositorySearchResult(
                    title="Lower",
                    url="https://example.org/lower",
                    source="Fake",
                ),
                RepositorySearchResult(
                    title="Higher",
                    url="https://example.org/higher",
                    source="Fake",
                ),
            ])

    response = search_repository_metadata(
        " malaria mortality ",
        providers=[FakeProvider()],
    )

    results = response.results
    assert [result.title for result in results] == ["Lower", "Higher"]
    assert [result.search_query for result in results] == [
        "malaria mortality",
        "malaria mortality",
    ]
    assert response.warnings == []


def test_search_repository_metadata_filters_invalid_results_before_returning():
    class MixedProvider:
        name = "mixed"

        def search(self, query):
            return RepositorySearchResponse(results=[
                RepositorySearchResult(
                    title="Valid result",
                    url="https://example.org/valid",
                    source="Mixed",
                ),
                RepositorySearchResult(
                    title="",
                    url="https://example.org/missing-title",
                    source="Mixed",
                ),
                RepositorySearchResult(
                    title="Invalid URL",
                    url="javascript:alert(1)",
                    source="Mixed",
                ),
                RepositorySearchResult(
                    title="Second valid result",
                    url="https://example.org/second-valid",
                    source="Mixed",
                ),
                RepositorySearchResult(
                    title="Third valid result",
                    url="https://example.org/third-valid",
                    source="Mixed",
                ),
            ])

    response = search_repository_metadata("malaria mortality", providers=[MixedProvider()])
    results = response.results

    assert len(results) == 3
    assert [result.title for result in results] == [
        "Valid result",
        "Second valid result",
        "Third valid result",
    ]
    assert len(response.warnings) == 1
    assert response.warnings[0].provider is None
    assert response.warnings[0].message == INVALID_METADATA_MESSAGE


def test_search_repository_metadata_returns_partial_results_when_one_provider_fails():
    class SuccessfulProvider:
        name = "successful"

        def search(self, query):
            assert query == "malaria mortality"
            return RepositorySearchResponse(results=[
                RepositorySearchResult(
                    title="Available result",
                    url="https://example.org/available",
                    source="Successful",
                )
            ])

    class FailingProvider:
        name = "failing"

        def search(self, query):
            raise ValueError("timeout")

    response = search_repository_metadata(
        "malaria mortality",
        providers=[FailingProvider(), SuccessfulProvider()],
    )

    results = response.results
    assert [result.title for result in results] == ["Available result"]
    assert len(response.warnings) == 1
    assert response.warnings[0].provider == "failing"
    assert response.warnings[0].message == PROVIDER_UNAVAILABLE_MESSAGE


def test_search_repository_metadata_counts_empty_provider_response_as_success():
    class EmptyProvider:
        name = "empty"

        def search(self, query):
            return RepositorySearchResponse()

    class FailingProvider:
        name = "failing"

        def search(self, query):
            raise ValueError("timeout")

    response = search_repository_metadata(
        "malaria mortality",
        providers=[EmptyProvider(), FailingProvider()],
    )

    assert response.results == []
    assert len(response.warnings) == 1
    assert response.warnings[0].provider == "failing"
    assert response.warnings[0].message == PROVIDER_UNAVAILABLE_MESSAGE


def test_search_repository_metadata_raises_only_when_all_providers_fail():
    class FirstFailingProvider:
        name = "first"

        def search(self, query):
            raise ValueError("timeout")

    class SecondFailingProvider:
        name = "second"

        def search(self, query):
            raise ValueError("bad response")

    try:
        search_repository_metadata(
            "malaria mortality",
            providers=[FirstFailingProvider(), SecondFailingProvider()],
        )
    except ValueError as exception:
        assert str(exception) == "All repository providers failed."
    else:
        raise AssertionError("Expected ValueError.")


def _datacite_record(identifier="valid", **attributes):
    return {
        "id": f"10.1234/{identifier}",
        "attributes": {"titles": [{"title": identifier}], **attributes},
    }


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("field", ["titles", "descriptions"])
def test_datacite_omits_only_the_record_with_unsafe_html(position, field):
    unsafe_html = "<div>" * 129 + "unsafe" + "</div>" * 129
    entry = {"title": unsafe_html} if field == "titles" else {"description": unsafe_html}
    items = [_datacite_record("first"), _datacite_record("second")]
    items.insert(position, _datacite_record("unsafe", **{field: [entry]}))

    response = search_repository_metadata(
        " health ",
        providers=[DataCiteRepositorySearchProvider(fetch_json=lambda _: {"data": items})],
    )

    assert [result.title for result in response.results] == ["first", "second"]
    assert [result.search_query for result in response.results] == ["health", "health"]
    assert response.warnings == [
        RepositorySearchWarning(
            code="invalid_repository_metadata",
            message=INVALID_METADATA_MESSAGE,
            provider="DataCite",
        )
    ]


@pytest.mark.parametrize("invalid", [None, [], {"attributes": []}, {"attributes": {}}])
def test_datacite_marks_unusable_records_as_incomplete(invalid):
    response = DataCiteRepositorySearchProvider(
        fetch_json=lambda _: {"data": [invalid, _datacite_record(), invalid]},
    ).search("health")

    assert len(response.results) == 1
    assert len(response.warnings) == 1
    assert response.warnings[0].code == "invalid_repository_metadata"
    assert response.warnings[0].provider == "DataCite"
    assert response.warnings[0].incomplete


@pytest.mark.parametrize("items, warning_count", [([], 0), ([None, {}], 1)])
def test_datacite_empty_and_all_invalid_batches_are_successful(items, warning_count):
    response = search_repository_metadata(
        "health",
        providers=[DataCiteRepositorySearchProvider(fetch_json=lambda _: {"data": items})],
    )

    assert response.results == []
    assert len(response.warnings) == warning_count
    if response.warnings:
        assert response.warnings[0].code == "invalid_repository_metadata"


def test_datacite_does_not_retain_warnings_between_searches():
    batches = iter([{"data": [None]}, {"data": [_datacite_record()]}])
    provider = DataCiteRepositorySearchProvider(fetch_json=lambda _: next(batches))

    assert len(provider.search("first").warnings) == 1
    response = provider.search("second")
    assert len(response.results) == 1
    assert response.warnings == []


@pytest.mark.parametrize(
    "failure",
    [
        asyncio.CancelledError(),
        ExecutionStopped(),
        PipelineFailure("stopped", diagnostics=[Diagnostic("processing_interrupted", "search")]),
        RuntimeError("unexpected bug"),
        ValueError("unexpected normalization bug"),
    ],
)
def test_datacite_does_not_hide_non_extraction_failures(monkeypatch, failure):
    def fail(_):
        raise failure

    monkeypatch.setattr(datacite, "_datacite_result", fail)
    provider = DataCiteRepositorySearchProvider(
        fetch_json=lambda _: {"data": [_datacite_record()]},
    )
    with pytest.raises(type(failure)) as raised:
        provider.search("health")
    assert raised.value is failure


def test_datacite_does_not_treat_fetch_failures_as_bad_records():
    failure = ExtractionError("failed before the record boundary")

    def fetch(_):
        raise failure

    with pytest.raises(ExtractionError) as raised:
        DataCiteRepositorySearchProvider(fetch_json=fetch).search("health")
    assert raised.value is failure


def _location_metadata(location):
    response = DataCiteRepositorySearchProvider(
        fetch_json=lambda _: {
            "data": [_datacite_record(geoLocations=[location])],
        },
    ).search("health")
    assert response.warnings == []
    assert len(response.results) == 1
    assert tuple(response.results[0].metadata) == DATASET_METADATA_KEYS
    return response.results[0].metadata


@pytest.mark.parametrize(
    "point, expected",
    [
        ({"pointLatitude": 0, "pointLongitude": 0}, "0, 0"),
        ({"pointLatitude": 46.5, "pointLongitude": 6.6}, "46.5, 6.6"),
        ({"pointLatitude": " 46.5 ", "pointLongitude": 6.6}, "46.5, 6.6"),
        ({"pointLatitude": -90, "pointLongitude": "180"}, "-90, 180"),
        ({"pointLatitude": "90", "pointLongitude": -180}, "90, -180"),
        ({"latitude": 0, "longitude": "-10.5"}, "0, -10.5"),
        ({"pointLatitude": False, "pointLongitude": 10}, "NA"),
        ({"pointLatitude": 10, "pointLongitude": True}, "NA"),
        ({"pointLatitude": 91, "pointLongitude": 10}, "NA"),
        ({"pointLatitude": 10, "pointLongitude": -181}, "NA"),
        ({"pointLatitude": "NaN", "pointLongitude": 10}, "NA"),
        ({"pointLatitude": float("inf"), "pointLongitude": 10}, "NA"),
        ({"pointLatitude": float("nan"), "pointLongitude": 10}, "NA"),
        ({"pointLatitude": 10**400, "pointLongitude": 10}, "NA"),
        ({"pointLatitude": "0" * 1_000, "pointLongitude": 10}, "NA"),
        ({"pointLatitude": "north", "pointLongitude": 10}, "NA"),
        ({"pointLatitude": "", "pointLongitude": 10}, "NA"),
        ({"pointLatitude": None, "pointLongitude": 10}, "NA"),
        ({"pointLatitude": [], "pointLongitude": 10}, "NA"),
        ({"pointLatitude": 0}, "NA"),
    ],
)
def test_datacite_validates_numeric_and_string_point_coordinates(point, expected):
    assert _location_metadata({"geoLocationPoint": point})["Geography"] == expected


@pytest.mark.parametrize(
    "box, expected",
    [
        (
            {"westBoundLongitude": 0, "eastBoundLongitude": "10",
             "southBoundLatitude": 0, "northBoundLatitude": 20.5},
            "0, 0 to 20.5, 10",
        ),
        (
            {"westBoundLongitude": 170, "eastBoundLongitude": -170,
             "southBoundLatitude": -20, "northBoundLatitude": 20},
            "-20, 170 to 20, -170",
        ),
        (
            {"westBoundLongitude": -180, "eastBoundLongitude": 180,
             "southBoundLatitude": -90, "northBoundLatitude": 90},
            "-90, -180 to 90, 180",
        ),
        (
            {"westBoundLongitude": 0, "eastBoundLongitude": 10,
             "southBoundLatitude": 20, "northBoundLatitude": 10},
            "NA",
        ),
        (
            {"westBoundLongitude": 0, "eastBoundLongitude": 181,
             "southBoundLatitude": 0, "northBoundLatitude": 10},
            "NA",
        ),
        (
            {"westBoundLongitude": 0, "eastBoundLongitude": 10,
             "southBoundLatitude": "-inf", "northBoundLatitude": 10},
            "NA",
        ),
        (
            {"westBoundLongitude": 0, "eastBoundLongitude": 10,
             "southBoundLatitude": False, "northBoundLatitude": 10},
            "NA",
        ),
        ({"westBoundLongitude": 0, "southBoundLatitude": 0, "northBoundLatitude": 10}, "NA"),
    ],
)
def test_datacite_validates_complete_boxes_and_accepts_antimeridian_crossing(box, expected):
    assert _location_metadata({"geoLocationBox": box})["Geography"] == expected
