from __future__ import annotations

import pytest

from collector.discovery.sitemap import (
    default_sitemap_candidates,
    discover_sitemap_entries,
    parse_sitemap,
    score_sitemap_url,
    sitemap_urls_from_robots,
)


def test_sitemap_urls_from_robots_extracts_absolute_and_relative_urls():
    robots_text = """
    User-agent: *
    Allow: /
    Sitemap: /sitemap.xml
    sitemap: https://example.org/extra-sitemap.xml # inline comment
    """

    sitemap_urls = sitemap_urls_from_robots(robots_text, "https://example.org/data/catalog?q=1")

    assert sitemap_urls == [
        "https://example.org/sitemap.xml",
        "https://example.org/extra-sitemap.xml",
    ]


def test_default_sitemap_candidates_use_site_root():
    assert default_sitemap_candidates("https://example.org/data/catalog?q=1") == [
        "https://example.org/robots.txt",
        "https://example.org/sitemap.xml",
    ]


def test_parse_sitemap_urlset_with_namespace():
    parsed = parse_sitemap(
        """
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.org/datasets/mortality</loc></url>
            <url><loc>/data/downloads/vaccination.csv</loc></url>
        </urlset>
        """,
        "https://example.org/sitemap.xml",
    )

    assert parsed.page_urls == (
        "https://example.org/datasets/mortality",
        "https://example.org/data/downloads/vaccination.csv",
    )
    assert parsed.nested_sitemap_urls == ()


def test_parse_sitemap_index_with_namespace():
    parsed = parse_sitemap(
        """
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.org/dataset-sitemap.xml</loc></sitemap>
            <sitemap><loc>/news-sitemap.xml</loc></sitemap>
        </sitemapindex>
        """,
        "https://example.org/sitemap.xml",
    )

    assert parsed.page_urls == ()
    assert parsed.nested_sitemap_urls == (
        "https://example.org/dataset-sitemap.xml",
        "https://example.org/news-sitemap.xml",
    )


def test_parse_sitemap_rejects_invalid_xml():
    with pytest.raises(ValueError, match="invalid"):
        parse_sitemap("<not-xml", "https://example.org/sitemap.xml")


def test_score_sitemap_url_prioritizes_dataset_patterns_without_dropping_other_pages():
    assert score_sitemap_url("https://example.org/datasets/mortality") > score_sitemap_url(
        "https://example.org/news/press-release"
    )
    assert score_sitemap_url("https://example.org/about") > 0


def test_discover_sitemap_entries_reads_robots_indexes_and_prioritizes_urls():
    responses = {
        "https://example.org/robots.txt": """
            User-agent: *
            Sitemap: https://example.org/sitemap-index.xml
        """,
        "https://example.org/sitemap-index.xml": """
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <sitemap><loc>https://example.org/pages-sitemap.xml</loc></sitemap>
            </sitemapindex>
        """,
        "https://example.org/pages-sitemap.xml": """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.org/about</loc></url>
                <url><loc>https://example.org/news/press-release</loc></url>
                <url><loc>https://example.org/datasets/mortality</loc></url>
                <url><loc>https://example.org/data/downloads/vaccination.csv?utm_source=x</loc></url>
                <url><loc>https://other.example.org/datasets/off-domain</loc></url>
            </urlset>
        """,
    }

    def fake_fetch_text(url: str) -> str:
        if url not in responses:
            raise ValueError(f"Unexpected URL: {url}")
        return responses[url]

    entries = discover_sitemap_entries(
        "https://example.org/data",
        fetch_text=fake_fetch_text,
        max_urls=10,
    )

    assert [entry.url for entry in entries] == [
        "https://example.org/data/downloads/vaccination.csv",
        "https://example.org/datasets/mortality",
        "https://example.org/about",
        "https://example.org/news/press-release",
    ]
    assert entries[0].priority > entries[-1].priority
    assert entries[0].source_sitemap_url == "https://example.org/pages-sitemap.xml"
