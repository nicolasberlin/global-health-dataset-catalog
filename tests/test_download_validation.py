import io
import json

import pytest

from collector.storage.models import DistributionCandidate, HTTPProbe
from collector.validation.downloads import probe_url, validate_distribution
from collector.validation.json_sample import read_json_prefix

URL = "https://example.org/data"


def json_validation(body, *, truncated=False, code=200, extra_headers=None):
    return validate_distribution(
        DistributionCandidate(URL, "JSON", .9),
        probe=lambda url, method, **kw: HTTPProbe(
            url, url, code,
            {"content-type": "application/json", **(extra_headers or {})},
            body if method == "GET" else b"", sample_truncated=truncated,
        ),
    )


@pytest.mark.parametrize("envelope", [None, "data", "results", "records", "value",
                                     "items", "features"])
def test_large_json_confirms_complete_records_in_bounded_prefix(envelope):
    records = [{"country": "CH", "value": index} for index in range(5000)]
    body = json.dumps(records if envelope is None else {envelope: records}).encode()
    assert len(body) > 65536
    result = json_validation(body[:65536], truncated=True)
    assert result.status == "available"
    assert "partial sample" in result.reason
    assert json_validation(body[:65536]).status == "unconfirmed"


@pytest.mark.parametrize("body,status", [
    (b'[{"value":1}, {"value":', "available"),
    (b'{"country":"CH","description":"unfinished', "available"),
    (b'{"data":[{"value":1},', "available"),
    (b'{"data":[{"value":', "unconfirmed"),
    (b'{"data":[],"description":"unfinished', "unconfirmed"),
    (b'{"data":"unfinished', "unconfirmed"),
    (b'{"count":100,"meta":{"note":"unfinished', "unconfirmed"),
    (b'{"error":"authentication required","data":[{"value":1},', "restricted"),
    (b'{"data":[1],"success":false,"more":[', "unconfirmed"),
    (b'{"data":[1],"error":"unfinished', "unconfirmed"),
    (b'{"data":[1],"error"', "unconfirmed"),
    (b'{"data":[1],"success":f', "unconfirmed"),
    (b'[{"value":1}, BROKEN', "unconfirmed"),
    (b'[{"value":1},]', "unconfirmed"),
    (b'{"value":1,}', "unconfirmed"),
    (b'[{"value":1}, "bad\\q', "unconfirmed"),
    (b'[{"value":1}, "bad\\ ', "unconfirmed"),
    (b'[{"value":1}, "bad\x01', "unconfirmed"),
    (b'[{"value":1}, "bad\xff', "unconfirmed"),
    (b'[{"value":1}, "cut\xc3', "available"),
    (b'[{"value":1}, "cut\\u12', "available"),
    (b'[{"value":1}, 1e+', "available"),
    (b'[{"value":1}, 01', "unconfirmed"),
    (b'[{"value":1}] garbage', "unconfirmed"),
    (b'[{"value":1}]\xc3', "unconfirmed"),
    (b'[{"value":1},' + b'[' * 70, "unconfirmed"),
])
def test_truncated_json_requires_evidence_and_valid_sampled_syntax(body, status):
    assert json_validation(body, truncated=True).status == status


def test_json_prefix_accepts_every_byte_boundary_in_valid_utf8_document():
    value = {"data": [{"text": 'é😊\\"\n\t', "number": -1.2e-7, "bool": True,
                       "null": None, "nested": [False, {}, [], 12.5]}] * 2}
    body = json.dumps(value, ensure_ascii=False).encode()
    for boundary in range(len(body) + 1):
        read_json_prefix(body[:boundary])
    assert read_json_prefix(body) == value


@pytest.mark.parametrize("content_range,status", [
    ("bytes 0-19/100", "available"),
    ("bytes 0-19/*", "available"),
    ("bytes 0-19/20", "unconfirmed"),
    ("bytes 10-29/100", "unconfirmed"),
    ("bytes 0-19/10", "unconfirmed"),
    ("", "unconfirmed"),
])
def test_json_range_must_confirm_a_truncated_initial_prefix(content_range, status):
    body = b'[{"value":1},'.ljust(20)
    assert len(body) == 20
    result = json_validation(body, code=206, extra_headers={"content-range": content_range})
    assert result.status == status


@pytest.mark.parametrize("length", [65535, 65536, 65537])
def test_probe_detects_truncation_when_server_ignores_range(monkeypatch, length):
    body = b'[{"value":1}]' + b' ' * (length - 13)
    reads = []

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "application/json"}

        def geturl(self):
            return URL

        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url",
                        lambda *a, **kw: Response(body))
    result = probe_url(URL, "GET", 1, 65536)
    assert reads == [65537]
    assert len(result.body_sample) == min(length, 65536)
    assert result.sample_truncated == (length > 65536)


def test_large_json_is_retained_by_collection_pipeline():
    from collector.classification.page import PageClassification
    from collector.discovery.adapters import DiscoveredPage
    from collector.main import collect_source_with_report

    class Classifier:
        def classify(self, page, distributions):
            return PageClassification(accepted=True, dataset_signals={})

    distribution = DistributionCandidate(URL, "JSON", .9)
    body = json.dumps({"data": [{"value": i} for i in range(10000)]}).encode()
    result = collect_source_with_report(
        URL, classifier=Classifier(),
        discover=lambda _: [DiscoveredPage(url=URL, discovery_method="test", title="Health data",
                                          distributions=(distribution,))],
        validate=lambda _: json_validation(body[:65536], truncated=True),
    )
    assert len(result.datasets) == 1
    assert result.report.invalid_distribution_count == 0


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
