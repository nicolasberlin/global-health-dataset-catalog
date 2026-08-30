from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from collector.classification.page import PageClassificationError
from collector.classification.repository import RepositoryClassification
from collector.extraction.dataset_metadata import DATASET_METADATA_KEYS
from collector.repository_search import (
    CLASSIFICATION_UNAVAILABLE_MESSAGE,
    INVALID_METADATA_MESSAGE,
    PROVIDER_UNAVAILABLE_MESSAGE,
    DataCiteRepositorySearchProvider,
    RepositorySearchResult,
    _number,
    classify_repository_results,
    search_repository_metadata,
)


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
                        "score": 0.93,
                    },
                }
            ]
        }

    results = DataCiteRepositorySearchProvider(
        fetch_json=fake_fetch_json,
        page_size=3,
    ).search("malaria mortality")

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
    assert result.relevance_score == 0.93
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

    results = DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search(
        "minimal"
    )

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

    results = DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search(
        "missing url"
    )

    assert len(results) == 1
    assert results[0].url == "https://doi.org/10.1234/missing-url"
    assert results[0].doi == "10.1234/missing-url"
    assert results[0].publisher == "Repository Publisher"
    assert results[0].date == "2024-06-30"
    assert results[0].relevance_score == 1.0


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

    results = DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search(
        "invalid url"
    )

    assert len(results) == 1
    assert results[0].url == "https://doi.org/10.1234/invalid-url"


def test_datacite_provider_fails_clearly_for_invalid_top_level_response():
    def fake_fetch_json(url):
        return {"errors": [{"title": "bad request"}]}

    try:
        DataCiteRepositorySearchProvider(fetch_json=fake_fetch_json).search("malaria")
    except ValueError as exception:
        assert str(exception) == "Invalid DataCite response shape: expected data list."
    else:
        raise AssertionError("Expected ValueError.")


def test_search_repository_metadata_sorts_provider_results_by_relevance():
    class FakeProvider:
        name = "fake"

        def search(self, query):
            assert query == "malaria mortality"
            return [
                RepositorySearchResult(
                    title="Lower",
                    url="https://example.org/lower",
                    source="Fake",
                    relevance_score=0.4,
                ),
                RepositorySearchResult(
                    title="Higher",
                    url="https://example.org/higher",
                    source="Fake",
                    relevance_score=0.9,
                ),
            ]

    response = search_repository_metadata(
        " malaria mortality ",
        providers=[FakeProvider()],
    )

    results = response.results
    assert [result.title for result in results] == ["Higher", "Lower"]
    assert [result.search_query for result in results] == [
        "malaria mortality",
        "malaria mortality",
    ]
    assert response.warnings == []


def test_number_rejects_boolean_values():
    assert _number(True) is None
    assert _number(False) is None


def test_search_repository_metadata_filters_invalid_results_before_returning():
    class MixedProvider:
        name = "mixed"

        def search(self, query):
            return [
                RepositorySearchResult(
                    title="Valid result",
                    url="https://example.org/valid",
                    source="Mixed",
                    relevance_score=0.8,
                ),
                RepositorySearchResult(
                    title="",
                    url="https://example.org/missing-title",
                    source="Mixed",
                    relevance_score=0.7,
                ),
                RepositorySearchResult(
                    title="Invalid URL",
                    url="javascript:alert(1)",
                    source="Mixed",
                    relevance_score=0.7,
                ),
                RepositorySearchResult(
                    title="Boolean score",
                    url="https://example.org/boolean-score",
                    source="Mixed",
                    relevance_score=True,
                ),
                RepositorySearchResult(
                    title="Out of range score",
                    url="https://example.org/out-of-range-score",
                    source="Mixed",
                    relevance_score=1.2,
                ),
            ]

    response = search_repository_metadata("malaria mortality", providers=[MixedProvider()])
    results = response.results

    assert len(results) == 1
    assert results[0].title == "Valid result"
    assert len(response.warnings) == 1
    assert response.warnings[0].provider is None
    assert response.warnings[0].message == INVALID_METADATA_MESSAGE


def test_search_repository_metadata_returns_partial_results_when_one_provider_fails():
    class SuccessfulProvider:
        name = "successful"

        def search(self, query):
            assert query == "malaria mortality"
            return [
                RepositorySearchResult(
                    title="Available result",
                    url="https://example.org/available",
                    source="Successful",
                    relevance_score=0.8,
                )
            ]

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
            return []

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


def test_classify_repository_results_keeps_items_when_one_classification_fails():
    class MixedClassifier:
        def classify(self, page):
            if page.url == "https://example.org/failing":
                raise PageClassificationError("bad LLM response")
            return RepositoryClassification(
                relevance_label="relevant",
                reason="The metadata matches the query.",
            )

    results, warnings = classify_repository_results(
        [
            RepositorySearchResult(
                title="Classified",
                url="https://example.org/classified",
                source="DataCite",
                relevance_score=0.9,
            ),
            RepositorySearchResult(
                title="Failing",
                url="https://example.org/failing",
                source="DataCite",
                relevance_score=0.8,
            ),
        ],
        MixedClassifier(),
    )

    assert len(results) == 2
    assert results[0].classification is not None
    assert results[0].classification.relevance_label == "relevant"
    assert not hasattr(results[0].classification, "health_label")
    assert results[1].classification is None
    assert len(warnings) == 1
    assert warnings[0].message == CLASSIFICATION_UNAVAILABLE_MESSAGE
