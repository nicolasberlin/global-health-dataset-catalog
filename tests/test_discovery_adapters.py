from __future__ import annotations

from collector.discovery.adapters import CKANAdapter, GenericWebsiteAdapter
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
