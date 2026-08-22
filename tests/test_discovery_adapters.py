from __future__ import annotations

from collector.discovery.adapters import (
    ADAPTERS,
    CKANAdapter,
    DataJsonAdapter,
    GenericWebsiteAdapter,
    SocrataAdapter,
)
from collector.discovery.manager import discover_source


def test_ckan_adapter_detects_status_endpoint():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"success": True, "result": {"site_title": "Example catalog"}}

    adapter = CKANAdapter(fetch_json=fake_fetch_json)

    assert adapter.detect("https://catalog.example.org") is True
    assert calls == ["https://catalog.example.org/api/3/action/status_show"]


def test_ckan_adapter_discovers_dataset_pages_and_resources():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "success": True,
            "result": {
                "results": [
                    {
                        "id": "abc-123",
                        "name": "covid-19-case-surveillance",
                        "title": "COVID-19 Case Surveillance Public Use Data",
                        "notes": "Public health dataset.",
                        "organization": {
                            "name": "cdc",
                            "title": "Centers for Disease Control and Prevention",
                        },
                        "resources": [
                            {
                                "name": "CSV download",
                                "format": "CSV",
                                "url": "https://data.example.org/covid.csv",
                                "mimetype": "text/csv",
                            },
                            {
                                "name": "Documentation",
                                "format": "PDF",
                                "url": "https://data.example.org/covid.pdf",
                                "mimetype": "application/pdf",
                            },
                        ],
                    }
                ]
            },
        }

    adapter = CKANAdapter(fetch_json=fake_fetch_json, rows=5)

    pages = adapter.discover("https://catalog.example.org")

    assert calls == ["https://catalog.example.org/api/3/action/package_search?rows=5"]
    assert len(pages) == 1

    page = pages[0]
    assert page.url == "https://catalog.example.org/dataset/covid-19-case-surveillance"
    assert page.discovery_method == "ckan"
    assert page.priority == 0.9
    assert page.title == "COVID-19 Case Surveillance Public Use Data"
    assert page.description == "Public health dataset."
    assert page.publisher == "Centers for Disease Control and Prevention"
    assert page.metadata == {
        "ckan_id": "abc-123",
        "ckan_name": "covid-19-case-surveillance",
    }

    assert len(page.distributions) == 1
    distribution = page.distributions[0]
    assert distribution.url == "https://data.example.org/covid.csv"
    assert distribution.format == "CSV"
    assert distribution.mime_type == "text/csv"
    assert distribution.signals["ckan_resource"] is True


def test_ckan_adapter_uses_source_query_to_filter_package_search():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"success": True, "result": {"results": [{"name": "mortality"}]}}

    adapter = CKANAdapter(fetch_json=fake_fetch_json, rows=5)

    pages = adapter.discover("https://catalog.example.org/search?q=health&ignored=yes")

    assert calls == ["https://catalog.example.org/api/3/action/package_search?q=health&rows=5"]
    assert pages[0].url == "https://catalog.example.org/dataset/mortality"


def test_socrata_adapter_detects_catalog_domain():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "results": [
                {
                    "resource": {
                        "id": "abcd-1234",
                        "name": "COVID-19 Case Surveillance Public Use Data",
                        "type": "dataset",
                    },
                    "metadata": {"domain": "data.cdc.gov"},
                }
            ]
        }

    adapter = SocrataAdapter(fetch_json=fake_fetch_json)

    assert adapter.detect("https://data.cdc.gov") is True
    assert calls == [
        "https://api.us.socrata.com/api/catalog/v1?"
        "domains=data.cdc.gov&search_context=data.cdc.gov&limit=1"
    ]


def test_socrata_adapter_discovers_dataset_pages_and_api_resources():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "results": [
                {
                    "resource": {
                        "id": "abcd-1234",
                        "name": "COVID-19 Case Surveillance Public Use Data",
                        "description": "Public health dataset.",
                        "attribution": "Centers for Disease Control and Prevention",
                        "type": "dataset",
                    },
                    "metadata": {"domain": "data.cdc.gov"},
                    "permalink": "https://data.cdc.gov/d/abcd-1234",
                    "link": (
                        "https://data.cdc.gov/Public-Health/"
                        "COVID-19-Case-Surveillance/abcd-1234"
                    ),
                },
                {
                    "resource": {
                        "id": "chart-1234",
                        "name": "COVID chart",
                        "type": "chart",
                    },
                    "metadata": {"domain": "data.cdc.gov"},
                },
            ]
        }

    adapter = SocrataAdapter(fetch_json=fake_fetch_json, rows=5)

    pages = adapter.discover("https://data.cdc.gov/browse?q=covid")

    assert calls == [
        "https://api.us.socrata.com/api/catalog/v1?"
        "domains=data.cdc.gov&search_context=data.cdc.gov&limit=5&q=covid"
    ]
    assert len(pages) == 1

    page = pages[0]
    assert page.url == "https://data.cdc.gov/d/abcd-1234"
    assert page.discovery_method == "socrata"
    assert page.priority == 0.9
    assert page.title == "COVID-19 Case Surveillance Public Use Data"
    assert page.description == "Public health dataset."
    assert page.publisher == "Centers for Disease Control and Prevention"
    assert page.metadata == {
        "socrata_id": "abcd-1234",
        "socrata_type": "dataset",
        "socrata_domain": "data.cdc.gov",
    }

    assert [distribution.format for distribution in page.distributions] == [
        "CSV",
        "JSON",
        "API",
    ]
    assert [distribution.url for distribution in page.distributions] == [
        "https://data.cdc.gov/resource/abcd-1234.csv",
        "https://data.cdc.gov/resource/abcd-1234.json",
        "https://data.cdc.gov/resource/abcd-1234.json?%24limit=1",
    ]
    assert all(
        distribution.signals["socrata_resource"] is True
        for distribution in page.distributions
    )


def test_socrata_adapter_falls_back_to_short_dataset_url_when_permalink_missing():
    def fake_fetch_json(url: str) -> dict[str, object]:
        return {
            "results": [
                {
                    "resource": {
                        "id": "wxyz-9876",
                        "name": "Vaccination health dataset",
                        "type": "dataset",
                    },
                    "metadata": {"domain": "data.cdc.gov"},
                }
            ]
        }

    pages = SocrataAdapter(fetch_json=fake_fetch_json).discover("https://data.cdc.gov")

    assert pages[0].url == "https://data.cdc.gov/d/wxyz-9876"
    assert pages[0].distributions[0].url == "https://data.cdc.gov/resource/wxyz-9876.csv"


def test_data_json_adapter_detects_project_open_data_catalog():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "dataset": [
                {
                    "identifier": "mortality-1",
                    "title": "Mortality health dataset",
                }
            ]
        }

    adapter = DataJsonAdapter(fetch_json=fake_fetch_json)

    assert adapter.detect("https://agency.example.gov/data/catalog") is True
    assert calls == ["https://agency.example.gov/data.json"]


def test_data_json_adapter_discovers_dataset_pages_and_distributions():
    calls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "dataset": [
                {
                    "identifier": "mortality-1",
                    "title": "Mortality by age and sex",
                    "description": "Official mortality health dataset.",
                    "publisher": {"name": "National Health Agency"},
                    "keyword": ["health", "mortality"],
                    "landingPage": "https://agency.example.gov/datasets/mortality",
                    "distribution": [
                        {
                            "title": "CSV download",
                            "downloadURL": "https://agency.example.gov/files/mortality.csv",
                            "mediaType": "text/csv",
                            "format": "CSV",
                        },
                        {
                            "title": "API endpoint",
                            "accessURL": "https://api.agency.example.gov/mortality",
                            "format": "API",
                        },
                        {
                            "title": "JSON export",
                            "downloadURL": "https://agency.example.gov/download?id=mortality",
                            "format": "application/json",
                        },
                        {
                            "title": "Methodology PDF",
                            "downloadURL": "https://agency.example.gov/files/method.pdf",
                            "mediaType": "application/pdf",
                            "format": "PDF",
                        },
                    ],
                },
                {
                    "identifier": "transport-1",
                    "title": "Road traffic counts",
                    "description": "Transport dataset.",
                    "landingPage": "https://agency.example.gov/datasets/roads",
                },
            ]
        }

    adapter = DataJsonAdapter(fetch_json=fake_fetch_json, rows=5)

    pages = adapter.discover("https://agency.example.gov/data.json?q=health")

    assert calls == ["https://agency.example.gov/data.json"]
    assert len(pages) == 1

    page = pages[0]
    assert page.url == "https://agency.example.gov/datasets/mortality"
    assert page.discovery_method == "data_json"
    assert page.priority == 0.9
    assert page.title == "Mortality by age and sex"
    assert page.description == "Official mortality health dataset."
    assert page.publisher == "National Health Agency"
    assert page.metadata == {
        "data_json_url": "https://agency.example.gov/data.json",
        "identifier": "mortality-1",
        "keywords": ["health", "mortality"],
    }

    assert [distribution.format for distribution in page.distributions] == ["CSV", "API", "JSON"]
    assert [distribution.url for distribution in page.distributions] == [
        "https://agency.example.gov/files/mortality.csv",
        "https://api.agency.example.gov/mortality",
        "https://agency.example.gov/download?id=mortality",
    ]
    assert page.distributions[0].mime_type == "text/csv"
    assert page.distributions[2].mime_type == "application/json"
    assert page.distributions[0].signals["data_json_distribution"] is True
    assert page.distributions[0].signals["download_url"] is True
    assert page.distributions[1].signals["access_url"] is True


def test_data_json_adapter_discovers_json_ld_dcat_graph():
    def fake_fetch_json(url: str) -> dict[str, object]:
        return {
            "@context": "https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld",
            "@graph": [
                {
                    "@type": "dcat:Dataset",
                    "@id": "https://agency.example.gov/id/dataset/vaccination",
                    "dct:title": "Vaccination health dataset",
                    "dct:description": "Vaccination coverage health indicators.",
                    "dct:publisher": {"foaf:name": "National Health Agency"},
                    "dcat:distribution": {
                        "dct:title": "JSON download",
                        "dcat:downloadURL": "https://agency.example.gov/files/vaccination.json",
                        "dcat:mediaType": "application/json",
                    },
                },
                {
                    "@type": "foaf:Document",
                    "@id": "https://agency.example.gov/docs",
                },
            ],
        }

    pages = DataJsonAdapter(fetch_json=fake_fetch_json).discover("https://agency.example.gov")

    assert len(pages) == 1
    assert pages[0].url == "https://agency.example.gov/id/dataset/vaccination"
    assert pages[0].title == "Vaccination health dataset"
    assert pages[0].publisher == "National Health Agency"
    assert pages[0].distributions[0].format == "JSON"


def test_data_json_adapter_uses_identifier_url_when_landing_page_missing():
    def fake_fetch_json(url: str) -> dict[str, object]:
        return {
            "dataset": [
                {
                    "identifier": "mortality-1",
                    "title": "Mortality health dataset",
                    "description": "Mortality health data.",
                }
            ]
        }

    pages = DataJsonAdapter(fetch_json=fake_fetch_json).discover("https://agency.example.gov")

    assert pages[0].url == "https://agency.example.gov/data.json?identifier=mortality-1"


def test_discovery_manager_prefers_ckan_before_generic_fallback():
    def fake_fetch_json(url: str) -> dict[str, object]:
        if url.endswith("/status_show"):
            return {"success": True, "result": {"site_title": "Example catalog"}}
        return {"success": True, "result": {"results": [{"name": "mortality"}]}}

    pages = discover_source(
        "https://catalog.example.org",
        adapters=(CKANAdapter(fetch_json=fake_fetch_json), GenericWebsiteAdapter()),
    )

    assert [page.discovery_method for page in pages] == ["ckan"]
    assert pages[0].url == "https://catalog.example.org/dataset/mortality"


def test_discovery_manager_uses_socrata_before_generic_fallback():
    def fake_ckan_fetch_json(url: str) -> dict[str, object]:
        raise ValueError("not a CKAN catalog")

    def fake_socrata_fetch_json(url: str) -> dict[str, object]:
        return {
            "results": [
                {
                    "resource": {
                        "id": "abcd-1234",
                        "name": "Mortality health dataset",
                        "type": "dataset",
                    },
                    "metadata": {"domain": "data.example.org"},
                }
            ]
        }

    pages = discover_source(
        "https://data.example.org",
        adapters=(
            CKANAdapter(fetch_json=fake_ckan_fetch_json),
            SocrataAdapter(fetch_json=fake_socrata_fetch_json),
            GenericWebsiteAdapter(),
        ),
    )

    assert [page.discovery_method for page in pages] == ["socrata"]
    assert pages[0].url == "https://data.example.org/d/abcd-1234"


def test_discovery_manager_uses_data_json_before_generic_fallback():
    def fake_ckan_fetch_json(url: str) -> dict[str, object]:
        raise ValueError("not a CKAN catalog")

    def fake_socrata_fetch_json(url: str) -> dict[str, object]:
        return {"results": []}

    def fake_data_json_fetch_json(url: str) -> dict[str, object]:
        return {
            "dataset": [
                {
                    "identifier": "mortality-1",
                    "title": "Mortality health dataset",
                    "landingPage": "https://agency.example.gov/datasets/mortality",
                }
            ]
        }

    pages = discover_source(
        "https://agency.example.gov",
        adapters=(
            CKANAdapter(fetch_json=fake_ckan_fetch_json),
            SocrataAdapter(fetch_json=fake_socrata_fetch_json),
            DataJsonAdapter(fetch_json=fake_data_json_fetch_json),
            GenericWebsiteAdapter(),
        ),
    )

    assert [page.discovery_method for page in pages] == ["data_json"]
    assert pages[0].url == "https://agency.example.gov/datasets/mortality"


def test_default_adapter_order_is_api_first_then_generic_fallback():
    assert [adapter.name for adapter in ADAPTERS] == [
        "ckan",
        "socrata",
        "data_json",
        "generic_website",
    ]


def test_discovery_manager_falls_back_to_generic_when_ckan_detection_fails():
    def fake_fetch_json(url: str) -> dict[str, object]:
        raise ValueError("not a CKAN catalog")

    def fake_fetch_text(url: str) -> str:
        raise ValueError("no sitemap available")

    pages = discover_source(
        "https://example.org/data",
        adapters=(
            CKANAdapter(fetch_json=fake_fetch_json),
            GenericWebsiteAdapter(fetch_text=fake_fetch_text),
        ),
    )

    assert [page.discovery_method for page in pages] == ["generic_website"]
    assert pages[0].url == "https://example.org/data"


def test_generic_website_adapter_discovers_sitemap_urls_before_source_url_fallback():
    responses = {
        "https://example.org/robots.txt": "Sitemap: https://example.org/sitemap.xml",
        "https://example.org/sitemap.xml": """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.org/news/update</loc></url>
                <url><loc>https://example.org/datasets/vaccination</loc></url>
            </urlset>
        """,
    }

    def fake_fetch_text(url: str) -> str:
        return responses[url]

    pages = GenericWebsiteAdapter(fetch_text=fake_fetch_text).discover("https://example.org")

    assert [page.url for page in pages] == [
        "https://example.org/datasets/vaccination",
        "https://example.org/news/update",
    ]
    assert [page.discovery_method for page in pages] == ["sitemap", "sitemap"]
    assert pages[0].priority > pages[1].priority
    assert pages[0].metadata["source_sitemap_url"] == "https://example.org/sitemap.xml"
