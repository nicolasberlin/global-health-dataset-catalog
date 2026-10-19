import json
from dataclasses import replace

import pytest

from collector.classification.page_llm_classifier import _build_llm_payload
from collector.extraction.distributions import extract_distributions
from collector.extraction.errors import ExtractionError
from collector.extraction.extractor import extract_page
from collector.extraction.limits import DEFAULT_EXTRACTION_LIMITS
from collector.storage.metadata import enrich_from_repository, metadata_evidence
from collector.storage.models import CollectedDataset, PageSnapshot

URL = "https://example.org/dataset/current"


def document(graph, prefix="", suffix=""):
    return (prefix + '<script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org", "@graph": graph})
            + "</script>" + suffix)


def dataset(node_id="https://example.org/dataset/current", **values):
    return {"@id": node_id, "@type": "Dataset", "name": "Selected dataset",
            "datePublished": "2026-10-01", "license": "CC0-1.0",
            "publisher": {"name": "Research institute"},
            "distribution": {"contentUrl": "https://example.org/current.csv",
                             "encodingFormat": "text/csv"}, **values}


def test_webpage_and_organization_metadata_do_not_replace_dataset_metadata():
    graph = [
        {"@type": "WebPage", "datePublished": "2001-01-01", "license": "Site Terms",
         "publisher": "Site operator", "spatialCoverage": "Site jurisdiction"},
        dataset(spatialCoverage="Dataset coverage"),
    ]
    page = extract_page(URL, document(graph, '<meta name="publisher" content="Site operator">'))
    assert page.publisher == "Research institute"
    assert page.date_of_publication == "2026-10-01"
    assert page.sharing_license == "CC0-1.0"
    assert page.geography == ("Dataset coverage",)
    assert [resource.url for resource in extract_distributions(page)] == [
        "https://example.org/current.csv",
    ]


def test_nested_organization_fields_do_not_fill_missing_dataset_fields():
    node = dataset()
    del node["license"], node["datePublished"]
    node["publisher"] = {"name": "Research institute", "license": "Company Terms",
                         "datePublished": "2000-01-01", "spatialCoverage": "Headquarters"}
    page = extract_page(URL, document([node]))
    assert page.sharing_license == page.date_of_publication == ""
    assert page.geography == ()


def test_multiple_datasets_select_url_and_only_its_resources():
    other = dataset("https://example.org/dataset/other", name="Other",
                    distribution={"contentUrl": "https://example.org/other.csv"})
    html = document([other, dataset()], "<title>Website title</title>",
                    '<a href="/unrelated.csv">Download unrelated data</a>')
    page = extract_page(URL, html)
    assert not page.dataset_metadata_ambiguous
    assert page.title == "Selected dataset"
    assert [resource.url for resource in extract_distributions(page)] == [
        "https://example.org/current.csv",
    ]


def test_classifier_evidence_excludes_other_datasets_and_global_recommendations():
    selected = dataset(name="Rainfall records", description="Monthly precipitation measurements.")
    other = dataset("https://example.org/other", name="Cancer HIV tuberculosis")
    html = document([other, selected], "<title>Cancer website</title>",
                    "<h2>Cancer by age and sex</h2><p>Recommended: HIV tuberculosis</p>")
    page = extract_page(URL, html)
    payload = _build_llm_payload(page, extract_distributions(page))
    evidence = json.dumps(payload).lower()
    assert page.text == "Rainfall records Monthly precipitation measurements."
    assert page.headings == page.diseases == page.demographic_information == ()
    for contaminant in ("cancer", "hiv", "tuberculosis", "age and sex"):
        assert contaminant not in evidence


@pytest.mark.parametrize("identity,field,matching", [
    ({"persistent_id": "10.1234/current"}, "identifier", "https://doi.org/10.1234/current"),
    ({"native_id": "record-42"}, "identifier", {"@type": "PropertyValue", "value": "record-42"}),
])
def test_expected_record_identity_selects_dataset_without_matching_landing_url(
    identity, field, matching,
):
    other = dataset("https://example.org/other", name="Other")
    selected = dataset("https://example.org/selected", **{field: matching})
    page = extract_page(URL, document([other, selected]), expected_identity=identity)
    assert page.title == "Selected dataset"
    assert page.dataset_json_ld[0]["@id"] == "https://example.org/selected"


def test_matching_doi_takes_precedence_over_another_datasets_url():
    other = dataset(URL, name="Other")
    selected = dataset("https://example.org/selected", identifier="10.1234/current")
    page = extract_page(URL, document([other, selected]),
                        expected_identity={"persistent_id": "10.1234/current"})
    assert page.title == "Selected dataset"


def test_native_id_can_disambiguate_records_sharing_one_doi():
    other = dataset("https://example.org/other", name="Other",
                    identifier=["10.1234/shared", "other-record"])
    selected = dataset("https://example.org/selected", identifier=["10.1234/shared", "record-42"])
    page = extract_page(URL, document([other, selected]),
                        expected_identity={"persistent_id": "10.1234/shared",
                                           "native_id": "record-42"})
    assert page.title == "Selected dataset"


def test_citation_doi_and_local_property_value_reference_select_dataset():
    graph = [dataset("https://example.org/other", name="Other"),
             dataset("https://example.org/selected", identifier={"@id": "#doi"}),
             {"@id": "#doi", "@type": "PropertyValue", "value": "10.1234/current"}]
    prefix = '<meta name="citation_doi" content="10.1234/current">'
    page = extract_page(URL, document(graph, prefix))
    assert page.dataset_json_ld[0]["@id"] == "https://example.org/selected"
    assert page.doi == "10.1234/current"


def test_local_references_share_one_scope_without_fetching_contexts():
    graph = [
        {"@type": "WebPage", "@id": URL, "mainEntity": {"@id": "#chosen"}},
        dataset("#other", name="Other"),
        dataset("#chosen", publisher={"@id": "#publisher"}, license={"@id": "#license"},
                distribution={"@id": "#file"}),
        {"@id": "#publisher", "@type": "Organization", "name": "Local publisher"},
        {"@id": "#license", "name": "CC-BY-4.0"},
        {"@id": "#file", "@type": "DataDownload", "contentUrl": "/chosen.csv"},
    ]
    page = extract_page(URL, document(graph))
    assert page.publisher == "Local publisher"
    assert page.sharing_license == "CC-BY-4.0"
    assert [resource.url for resource in extract_distributions(page)] == [
        "https://example.org/chosen.csv",
    ]


def test_inline_webpage_main_entity_without_id_selects_the_embedded_dataset():
    selected = dataset(distribution={"contentUrl": "/chosen.csv"})
    del selected["@id"]
    graph = [{"@type": "WebPage", "@id": URL, "mainEntity": selected},
             dataset("https://example.org/other", name="Other")]
    page = extract_page(URL, document(graph))
    assert not page.dataset_metadata_ambiguous
    assert page.title == "Selected dataset"
    assert [resource.url for resource in extract_distributions(page)] == [
        "https://example.org/chosen.csv",
    ]


def test_multiple_unmatched_datasets_leave_metadata_and_resources_unassigned():
    graph = [dataset("https://example.org/first"), dataset("https://example.org/second")]
    html = document(graph, '<title>Site title</title><meta name="publisher" content="Site">',
                    '<h1>Cancer by age</h1><a href="/data.csv">Download data</a>')
    page = extract_page(URL, html)
    assert page.dataset_metadata_ambiguous
    assert page.title == page.h1 == page.publisher == page.date_of_publication == ""
    assert page.doi == page.sharing_license == page.description_of_dataset == ""
    assert page.diseases == page.demographic_information == page.geography == ()
    assert extract_distributions(page) == []
    evidence = metadata_evidence(page, kind="page", source_url=URL)
    assert evidence == {"dataset_identity": [{"kind": "ambiguous_json_ld", "source_url": URL}]}
    collected = CollectedDataset(URL, "", "", "", "", "", {}, metadata_provenance=evidence)
    enriched = enrich_from_repository(collected, {
        "url": URL, "publication_date": "2026-10-01", "doi": "10.1234/current",
        "metadata": {"Sharing license": "CC0-1.0"},
    })
    assert enriched is collected


def test_shared_organization_reference_is_not_dataset_identity_evidence():
    graph = [dataset("https://example.org/first", publisher={"@id": "#org"}),
             dataset("https://example.org/second", publisher={"@id": "#org"}),
             {"@id": "#org", "@type": "Organization", "name": "Shared institute"}]
    assert extract_page(URL, document(graph)).dataset_metadata_ambiguous


def test_legacy_page_snapshot_scopes_schema_resources_locally():
    page = PageSnapshot(URL, URL, json_ld=({"@graph": [
        dataset("https://example.org/other", distribution={"contentUrl": "/other.csv"}),
        dataset(),
    ]},))
    assert [resource.url for resource in extract_distributions(page)] == [
        "https://example.org/current.csv",
    ]


def test_cyclic_local_reference_does_not_recurse_forever():
    page = extract_page(URL, document([dataset(publisher={"@id": "#org"}),
                                      {"@id": "#org", "name": "Institute",
                                       "parentOrganization": {"@id": "#org"}}]))
    assert page.publisher == "Institute"


def test_reference_expansion_is_bounded_independently_of_raw_graph_size():
    graph = [dataset(publisher=[{"@id": "#org"}] * 10),
             {"@id": "#org", "name": "x" * 100}]
    bounds = replace(DEFAULT_EXTRACTION_LIMITS, max_json_ld_chars=1_000)
    assert len(json.dumps(graph)) < bounds.max_json_ld_chars
    with pytest.raises(ExtractionError, match="Resolved JSON-LD size limit"):
        extract_page(URL, document(graph), limits=bounds)
