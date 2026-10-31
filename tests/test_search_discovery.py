"""Discovery admits individually safe candidates before quota and API boundaries."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from app.api.schemas.search import RepositoryCandidateView
from app.policies.quotas import WorkAdmission
from app.workers.search.discovery import lookup_local, prepare_repository_candidates

from collector.classification.repository import (
    MAX_REPOSITORY_DESCRIPTION_CHARS,
    MAX_REPOSITORY_KEYWORD_CHARS,
    MAX_REPOSITORY_KEYWORDS,
    MAX_REPOSITORY_METADATA_BYTES,
    MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS,
    MAX_REPOSITORY_METADATA_VALUE_CHARS,
    MAX_REPOSITORY_TITLE_CHARS,
)
from collector.extraction.dataset_metadata import DATASET_METADATA_KEYS
from collector.repository_search import (
    DataCiteRepositorySearchProvider,
    RepositorySearchResponse,
    RepositorySearchResult,
    RepositorySearchWarning,
    search_repository_metadata,
)
from collector.url_utils import normalize_http_url


def candidate(name="healthy", **changes):
    return replace(
        RepositorySearchResult(
            title=name,
            url=f"https://example.org/{name}",
            source="DataCite",
        ),
        **changes,
    )


def prepare(items, *, warnings=(), max_candidates=None):
    return prepare_repository_candidates(
        RepositorySearchResponse(results=items, warnings=list(warnings)),
        "malaria",
        WorkAdmission((), max_candidates=max_candidates),
    )


def public_item(item):
    fields = asdict(item)
    fields.pop("search_query")
    return RepositoryCandidateView(
        candidate_id=uuid4(),
        search_id=uuid4(),
        **fields,
    )


def assert_invalid_warning(result):
    invalid = [
        warning for warning in result.warnings if warning.code == "invalid_repository_metadata"
    ]
    assert len(invalid) == 1 and invalid[0].incomplete
    assert not result.complete


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize(
    "invalid",
    [
        candidate("invalid", title="Bad\x00title"),
        candidate("invalid", title="Bad\ud800title"),
        candidate("invalid", url="https://example.org/" + "a" * 2100),
    ],
    ids=["nul", "surrogate", "long-url"],
)
def test_invalid_candidate_does_not_discard_healthy_neighbors(position, invalid):
    items = [candidate("first"), candidate("second")]
    items.insert(position, invalid)

    result = prepare(items)

    assert [item.title for item in result.candidates] == ["first", "second"]
    assert_invalid_warning(result)
    for item in result.candidates:
        public_item(item)


@pytest.mark.parametrize(
    "unsafe", ["\x00", "\ud800", "\udfff"], ids=["nul", "high-surrogate", "low-surrogate"]
)
@pytest.mark.parametrize(
    "field",
    [
        "title",
        "url",
        "description",
        "source",
        "publisher",
        "date",
        "doi",
        "keywords",
        "metadata",
    ],
)
def test_all_stored_provider_text_is_checked_before_preparation(field, unsafe):
    value = f"Before{unsafe}after"
    if field == "keywords":
        value = ["safe", value]
    elif field == "metadata":
        value = {"Geography": value}
    elif field == "url":
        value = f"https://example.org/?q={value}"

    result = prepare([candidate("invalid", **{field: value}), candidate()])

    assert [item.title for item in result.candidates] == ["healthy"]
    assert_invalid_warning(result)


@pytest.mark.parametrize("unsafe", ["\x00", "\ud800"], ids=["nul", "surrogate"])
@pytest.mark.parametrize("field", ["title", "url", "publisher", "geography", "keywords"])
def test_datacite_records_are_filtered_without_losing_valid_results(field, unsafe):
    value = f"Before{unsafe}after"
    attributes = {"url": "https://example.org/invalid", "titles": [{"title": "Invalid"}]}
    if field == "title":
        attributes["titles"] = [{"title": value}]
    elif field == "url":
        attributes["url"] = f"https://example.org/?q={value}"
    elif field == "publisher":
        attributes["publisher"] = {"name": value}
    elif field == "geography":
        attributes["geoLocations"] = [{"geoLocationPlace": value}]
    else:
        attributes["subjects"] = [{"subject": value}]
    records = [
        {"attributes": {"titles": [{"title": "First"}], "url": "https://example.org/first"}},
        {"attributes": attributes},
        {"attributes": {"titles": [{"title": "Second"}], "url": "https://example.org/second"}},
    ]
    provider = DataCiteRepositorySearchProvider(fetch_json=lambda _: {"data": records})

    response = search_repository_metadata("malaria", providers=[provider])
    assert [item.title for item in response.results] == ["First", "Second"]
    assert [warning.code for warning in response.warnings] == ["invalid_repository_metadata"]
    result = prepare_repository_candidates(response, "malaria", WorkAdmission(()))

    assert [item.title for item in result.candidates] == ["First", "Second"]
    assert_invalid_warning(result)


def test_datacite_url_outside_public_contract_is_omitted_before_preparation():
    records = [
        {
            "attributes": {
                "titles": [{"title": "Invalid"}],
                "url": "https://example.org/" + "a" * 2100,
            },
        },
        {"attributes": {"titles": [{"title": "Healthy"}], "url": "https://example.org/healthy"}},
    ]
    provider = DataCiteRepositorySearchProvider(fetch_json=lambda _: {"data": records})

    response = search_repository_metadata("malaria", providers=[provider])

    assert [item.title for item in response.results] == ["Healthy"]
    assert [warning.code for warning in response.warnings] == ["invalid_repository_metadata"]
    result = prepare_repository_candidates(response, "malaria", WorkAdmission(()))
    assert_invalid_warning(result)
    public_item(result.candidates[0])


@pytest.mark.parametrize("length", [2083, 2084])
def test_url_limit_matches_public_api_without_truncating_the_url(length):
    prefix = "https://example.org/"
    url = prefix + "a" * (length - len(prefix))

    result = prepare([candidate(url=url)])

    if length == 2083:
        assert result.candidates[0].url == url
        assert str(public_item(result.candidates[0]).url) == url
        assert result.warnings == []
    else:
        assert result.candidates == []
        assert_invalid_warning(result)


def test_url_length_is_checked_after_query_normalization_expands_unicode():
    url = "https://example.org/?q=" + "é" * 400
    assert len(url) < 2083 < len(normalize_http_url(url))

    result = prepare([candidate("invalid", url=url), candidate()])

    assert [item.title for item in result.candidates] == ["healthy"]
    assert_invalid_warning(result)


def test_unicode_path_keeps_the_original_url_accepted_by_the_public_model():
    url = "https://example.org/" + "é" * 1000
    assert len(url) < 2083

    result = prepare([candidate(url=url)])

    assert result.candidates[0].url == url
    assert result.warnings == [] and result.complete
    assert len(str(public_item(result.candidates[0]).url)) > 2083


@pytest.mark.parametrize(
    "url",
    [
        "https://exa%mple.org/a",
        "https://exa\x01mple.org/a",
    ],
    ids=["percent-in-host", "control-in-host"],
)
def test_urls_rejected_by_public_model_do_not_discard_healthy_candidates(url):
    result = prepare([candidate("invalid", url=url), candidate()])

    assert [item.title for item in result.candidates] == ["healthy"]
    assert_invalid_warning(result)
    public_item(result.candidates[0])


def test_safe_unicode_survives_and_query_is_supplied_by_the_server():
    text = "Données de santé — 日本語 😀\nsecond line"
    item = candidate(
        title=text,
        description=text,
        publisher=text,
        keywords=[text],
        metadata={"Description of dataset": text},
        search_query="provider query",
    )

    result = prepare([item])

    saved = result.candidates[0]
    assert saved.title == text and saved.publisher == text
    assert saved.keywords == [text]
    assert saved.metadata["Description of dataset"] == text
    assert saved.search_query == "malaria"
    assert result.warnings == [] and result.complete
    public_item(saved)


def test_invalid_metadata_warning_preserves_existing_provider_warnings():
    inherited = RepositorySearchWarning(provider="Other provider")

    result = prepare([candidate(title="Bad\x00title")], warnings=[inherited])

    assert result.warnings[0] == inherited
    assert_invalid_warning(result)


@pytest.mark.parametrize(
    "character", ["a", "😀", "\x01"], ids=["ascii", "multibyte", "json-escaped-control"]
)
def test_metadata_limits_fit_the_public_contract_in_utf8_bytes(character):
    metadata = {key: character * 100_000 for key in DATASET_METADATA_KEYS}
    item = candidate(
        title="t" * (MAX_REPOSITORY_TITLE_CHARS + 1),
        description="d" * (MAX_REPOSITORY_DESCRIPTION_CHARS + 1),
        keywords=["k" * (MAX_REPOSITORY_KEYWORD_CHARS + 1)] * (MAX_REPOSITORY_KEYWORDS + 1),
        metadata={**metadata, "unrecognized": "discarded"},
    )

    result = prepare([item])

    saved = result.candidates[0]
    assert len(saved.title) <= MAX_REPOSITORY_TITLE_CHARS
    assert len(saved.description) <= MAX_REPOSITORY_DESCRIPTION_CHARS
    assert len(saved.keywords) <= MAX_REPOSITORY_KEYWORDS
    assert all(len(keyword) <= MAX_REPOSITORY_KEYWORD_CHARS for keyword in saved.keywords)
    assert set(saved.metadata) == set(DATASET_METADATA_KEYS)
    assert all(
        len(value)
        <= (
            MAX_REPOSITORY_METADATA_DESCRIPTION_CHARS
            if key == "Description of dataset"
            else MAX_REPOSITORY_METADATA_VALUE_CHARS
        )
        for key, value in saved.metadata.items()
    )
    encoded = json.dumps(saved.metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= MAX_REPOSITORY_METADATA_BYTES
    assert all(value for value in saved.metadata.values())
    public_item(saved)


def test_deduplication_precedes_candidate_cap_and_preserves_scope_semantics():
    first = candidate("first")
    second = candidate("second")

    result = prepare([first, first, second, candidate("third")], max_candidates=2)

    assert [item.title for item in result.candidates] == ["first", "second"]
    assert [warning.code for warning in result.warnings] == ["search_scope_limited"]
    assert result.complete and not result.warnings[0].incomplete
    assert result.diagnostics[0]["recovery"] == "none"


def test_preparation_does_not_hide_unexpected_failures():
    failure = RuntimeError("unexpected normalization failure")

    def broken_bound(item, *, search_query):
        raise failure

    with pytest.raises(RuntimeError) as caught:
        prepare_repository_candidates(
            RepositorySearchResponse(results=[candidate()]),
            "malaria",
            WorkAdmission(()),
            bound=broken_bound,
        )
    assert caught.value is failure


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["", "  ", "dataset data databases"])
async def test_local_lookup_skips_database_when_no_meaningful_terms_remain(query):
    async def forbidden_lookup(normalized):
        pytest.fail("An empty normalized query must not access the database")

    assert await lookup_local(query, lookup=forbidden_lookup) == []


@pytest.mark.anyio
async def test_local_lookup_normalizes_query_and_propagates_database_failures():
    failure = RuntimeError("database is unavailable")
    calls = []

    async def unavailable(normalized):
        calls.append(normalized)
        raise failure

    with pytest.raises(RuntimeError) as caught:
        await lookup_local("  malaria datasets  ", lookup=unavailable)
    assert calls == ["malaria"]
    assert caught.value is failure
