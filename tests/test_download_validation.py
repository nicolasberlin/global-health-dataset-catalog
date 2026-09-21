import pytest

from collector.storage.models import DistributionCandidate, HTTPProbe
from collector.validation.downloads import validate_distribution

URL = "https://example.org/data"


@pytest.mark.parametrize("code,mime,body,status", [
    (200, "text/html", b'<html><input type="password"></html>', "restricted"),
    (200, "text/html", b"<html>CAPTCHA</html>", "restricted"),
    (200, "text/csv", b"<html>Log in</html>", "restricted"),
    (200, "text/html", b"<html>Documentation</html>", "unconfirmed"),
    (204, "application/json", b"", "unconfirmed"),
    (205, "application/json", b"", "unconfirmed"),
    (200, "text/csv", b"", "unconfirmed"),
    (200, "application/json", b'{"error":"authentication required"}', "restricted"),
    (200, "application/json", b'{"success":false,"message":"Bad request"}', "unconfirmed"),
    (200, "application/json", b'{"error":null,"data":[{"value":1}]}', "available"),
    (200, "application/json", b'{"data":[]}', "unconfirmed"),
    (200, "application/json", b'{"status":"ok"}', "unconfirmed"),
    (200, "application/json", b'{"data":[{"value":', "unconfirmed"),
    (401, "application/json", b"", "restricted"),
    (403, "text/html", b"", "restricted"),
    (404, "text/html", b"", "unavailable"),
    (410, "text/html", b"", "unavailable"),
    (429, "text/html", b"", "unconfirmed"),
    (503, "text/html", b"", "unconfirmed"),
    (None, "", b"", "unconfirmed"),
])
def test_access_status(code, mime, body, status):
    calls = []

    def probe(url, method, **kwargs):
        calls.append(method)
        return HTTPProbe(url, url, code, {"content-type": mime},
                         body if method == "GET" else b"")

    result = validate_distribution(DistributionCandidate(URL, "API", .9), probe=probe)
    assert result.status == status
    assert result.ok == (status == "available")
    assert result.reason
    if code == 200:
        assert calls == ["HEAD", "GET"]


@pytest.mark.parametrize("content_range,head_size,head_etag,expected", [
    ("bytes 0-65535/4200000000", "", '"v1"', 4_200_000_000),
    ("bytes 0-65535/*", "", '"v1"', None),
    ("bytes 0-65535/*", "4200000000", '"v1"', 4_200_000_000),
    ("bytes 0-65535/*", "4200000000", '"old"', None),
    ("bytes 50-10/100", "", '"v1"', None),
    ("bytes 0-65535/12", "", '"v1"', None),
    ("bytes 0-65535/99999999999999999999", "", '"v1"', None),
])
def test_partial_response_uses_total_size(content_range, head_size, head_etag, expected):
    def probe(url, method, **kwargs):
        if method == "HEAD":
            return HTTPProbe(url, url, 200, {"content-type": "text/csv",
                             "content-length": head_size, "etag": head_etag})
        return HTTPProbe(url, url, 206, {"content-type": "text/csv",
                         "content-length": "65536", "content-range": content_range,
                         "etag": '"v1"'}, b"country,value\nCH,10\n")

    result = validate_distribution(DistributionCandidate(URL, "CSV", .9), probe=probe)
    assert result.size_bytes == expected


def test_failed_validations_survive_dataset_rejection():
    from collector.classification.page import PageClassification
    from collector.discovery.adapters import DiscoveredPage
    from collector.main import collect_source_with_report

    class Classifier:
        def classify(self, page, distributions):
            return PageClassification(accepted=True, dataset_signals={})

    distribution = DistributionCandidate(URL, "API", .9)
    result = collect_source_with_report(
        URL, classifier=Classifier(),
        discover=lambda _: [DiscoveredPage(url=URL, discovery_method="test", title="Health data",
                                          distributions=(distribution,))],
        validate=lambda item: validate_distribution(
            item, probe=lambda url, **kw: HTTPProbe(url, url, 401)),
    )
    assert result.datasets == []
    assert result.report.invalid_distribution_count == 1
    assert result.report.validation_failures[0].status == "restricted"
    assert result.report.validation_failures[0].reason
