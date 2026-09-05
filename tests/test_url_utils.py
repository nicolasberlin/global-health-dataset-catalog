from __future__ import annotations

import pytest

from collector.url_utils import (
    normalize_http_url,
    require_http_url,
    select_dataset_url,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Example.org/data#section", "https://example.org/data"),
        ("http://example.org/data", "http://example.org/data"),
        ("/dataset", None),
        ("javascript:alert(1)", None),
        ("file:///etc/passwd", None),
        ("data:text/html,test", None),
        ("https://example.org:invalid/data", None),
        ("https://example.org:99999/data", None),
        ("https://user:password@example.org/data", None),
        ("https://example.org\\@attacker.test/data", None),
        ("https://example.org/data\nnext", None),
        ("https://exa mple.org/data", None),
        ("https://example.org/data set", None),
    ],
)
def test_normalize_http_url(value, expected):
    assert normalize_http_url(value) == expected


def test_normalize_http_url_resolves_relative_values_against_base_url():
    assert normalize_http_url("../dataset", "https://example.org/catalog/page") == (
        "https://example.org/dataset"
    )


def test_require_http_url_raises_for_invalid_url():
    with pytest.raises(ValueError, match=r"valid HTTP\(S\) URL"):
        require_http_url("javascript:alert(1)")


def test_collected_url_normalization_is_stable():
    assert require_http_url(" HTTPS://Example.org/data?utm_source=test#section ") == (
        "https://example.org/data"
    )


def test_select_dataset_url_accepts_same_hostname_canonical():
    assert select_dataset_url(
        "https://example.org/catalog/page",
        "https://example.org:8443/dataset",
    ) == "https://example.org:8443/dataset"


@pytest.mark.parametrize(
    "canonical_href",
    [
        "https://other.example/dataset",
        "javascript:alert(1)",
        "https://example.org:invalid/dataset",
        "https://user@example.org/dataset",
    ],
)
def test_select_dataset_url_falls_back_for_untrusted_canonical(canonical_href):
    assert select_dataset_url(
        "https://example.org/catalog/page",
        canonical_href,
    ) == "https://example.org/catalog/page"
