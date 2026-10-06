import codecs
import gzip
import io
import json
import zipfile
from urllib.error import HTTPError

import pytest

from collector.storage.models import DistributionCandidate, HTTPProbe
from collector.validation.downloads import probe_url, validate_distribution
from collector.validation.json_sample import read_json_prefix

URL = "https://example.org/data"


def sample_validation(body, fmt="CSV", *, truncated=False, code=200, headers=None):
    url = f"{URL}.{fmt.lower()}"
    return validate_distribution(
        DistributionCandidate(url, fmt, .9),
        probe=lambda url, method, **kw: HTTPProbe(
            url, url, code, headers or {}, body if method == "GET" else b"",
            sample_truncated=truncated,
        ),
    )


def zip_sample():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.csv", "country,value\nCH,1\n" * 100)
    return output.getvalue()


@pytest.mark.parametrize("fmt", [
    "CSV", "TSV", "ZIP", "GZ", "PARQUET", "XLS", "XLSX", "XML", "JSONL",
    "SAV", "DTA", "SAS7BDAT", "UNKNOWN",
])
@pytest.mark.parametrize("body", [
    b"Service temporarily unavailable", b"Error, please try again", b"Access denied",
    b"", b"\x00\xff\x01garbage", b"country,value\n", b"country,mortality\\nGBR,10\\n",
])
def test_names_and_headers_cannot_confirm_arbitrary_content(fmt, body):
    result = sample_validation(body, fmt, headers={
        "content-type": f"application/{fmt.lower()}",
        "content-disposition": f'attachment; filename="data.{fmt.lower()}"',
    })
    assert result.status == "unconfirmed"
    assert not result.ok


@pytest.mark.parametrize("text,fmt", [
    ("country,value\nCH,1\n", "CSV"),
    ("country;value\r\nCH;1\r\n", "CSV"),
    ('country,description\nCH,"hello, world"\n', "CSV"),
    ('country,description\nCH,"two\nlines"\n', "CSV"),
    ("country\tvalue\nCH\t1", "TSV"),
    ("country,value\nCH,1", "CSV"),
])
def test_plausible_tables_refine_incorrect_advertised_formats(text, fmt):
    result = sample_validation(text.encode(), "ZIP", headers={"content-type": "application/zip"})
    assert result.status == "available"
    assert result.format == fmt
    assert "full file was not validated" in result.reason


@pytest.mark.parametrize("encoding,bom", [
    ("utf-8", b""), ("utf-8", codecs.BOM_UTF8),
    ("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE),
    ("utf-32-le", codecs.BOM_UTF32_LE), ("utf-32-be", codecs.BOM_UTF32_BE),
])
def test_tabular_encodings_and_cut_final_characters(encoding, bom):
    body = bom + "country,value\r\nPérou,1\r\n".encode(encoding)
    assert sample_validation(body).ok
    cut = body + "Chili,é".encode(encoding)[:-1]
    assert sample_validation(cut, truncated=True).ok
    assert not sample_validation(cut).ok


@pytest.mark.parametrize("body,truncated", [
    (b"country,value\nCH,", True),
    (b"country,value\nCH,1,extra\n", False),
    (b"country,value\nCH,1\nBOGUS\n", True),
    (b'country,value\nCH,"unterminated', False),
    (b'country,value\nCH,1\nUS,"bad"junk\n', True),
    (b"country,value\nCH,1\nUS,\xff\n", True),
    (b"country,value\nCH,1\nUS,\x00\n", True),
    ("country,value\nPérou,1\n".encode("latin-1"), False),
    ("country,value\nCH,1\n".encode("utf-16-le"), False),
    (b"a,b\tc\n1,2\t3\n", False),
    ("country,value\nCH,cut\u2028field".encode(), True),
])
def test_ambiguous_or_malformed_tables_remain_unconfirmed(body, truncated):
    assert not sample_validation(body, truncated=truncated).ok


@pytest.mark.parametrize("suffix", [b"US,", b'US,"unfinished', b'US,"multi\nline'])
def test_complete_records_can_confirm_a_truncated_table(suffix):
    assert sample_validation(b"country,value\nCH,1\n" + suffix, truncated=True).ok


@pytest.mark.parametrize("fmt,body", [
    ("ZIP", zip_sample()), ("GZ", gzip.compress(b"country,value\nCH,1\n")),
    ("PARQUET", b"PAR1\x15\x04\x15\x10"),
])
def test_binary_prefix_evidence_does_not_claim_whole_file_validity(fmt, body):
    prefix = body[:45] if fmt == "ZIP" else body[:12]
    result = sample_validation(prefix, "CSV", truncated=True)
    assert result.ok
    assert result.format == fmt
    assert "full file was not validated" in result.reason


@pytest.mark.parametrize("body,fmt", [
    (b"PK\x03\x04", "ZIP"), (zip_sample()[:32], "ZIP"),
    (b"PK\x03\x04" + b"\x00" * 40, "ZIP"),
    (b" " + zip_sample(), "ZIP"), (b"PK\x05\x06" + b"\x00" * 18, "ZIP"),
    (b"\x1f\x8b\x08", "GZ"), (b"\x1f\x8b\x08\xe0" + b"\x00" * 20, "GZ"),
    (b"\x1f\x8b\x08\x08" + b"\x00" * 6 + b"unfinished-name", "GZ"),
    (b"PAR1", "PARQUET"), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "XLS"),
    (b"<data><value>1</value></data>", "XML"),
])
def test_short_invalid_or_ambiguous_binary_and_unsupported_samples(body, fmt):
    assert not sample_validation(body, fmt, truncated=True).ok


def test_zip_container_does_not_prove_xlsx_contents():
    result = sample_validation(zip_sample(), "XLSX")
    assert result.ok
    assert result.format == "ZIP"


@pytest.mark.parametrize("content_range,expected", [
    ("bytes 0-21/100", True), ("bytes 0-21/*", True),
    ("bytes 1-22/100", False), ("", False), ("bytes 0-30/100", False),
])
def test_non_json_ranges_must_confirm_initial_bytes(content_range, expected):
    body = b"country,value\nCH,1\nUS,"
    assert len(body) == 22
    result = sample_validation(body, code=206, headers={"content-range": content_range})
    assert result.ok is expected


def test_json_content_at_csv_url_keeps_json_validation_and_refines_format():
    result = sample_validation(b'{"data":[{"country":"CH"}]}')
    assert result.ok
    assert result.format == "JSON"
    assert not sample_validation(b'{"error":"Service unavailable"}').ok


def test_probe_uses_configured_user_agent_for_head_and_bounded_get(monkeypatch):
    requests = []
    reads = []

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "text/csv"}

        def geturl(self):
            return URL

        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def open_url(request, *, timeout):
        requests.append((request, timeout))
        return Response(b"country,value\nCH,1\n" * 100)

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", open_url)
    result = validate_distribution(
        DistributionCandidate(URL, "CSV", .9), timeout=1.25, max_sample_bytes=64,
        user_agent="ConfiguredCollector/1",
    )
    assert result.ok
    assert [request.get_method() for request, _ in requests] == ["HEAD", "GET"]
    assert all(timeout == 1.25 for _, timeout in requests)
    assert all(request.get_header("User-agent") == "ConfiguredCollector/1"
               for request, _ in requests)
    assert requests[1][0].get_header("Range") == "bytes=0-63"
    assert reads == [65]


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


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
@pytest.mark.parametrize("truncated", [False, True])
def test_non_json_numeric_constants_never_confirm_data(constant, truncated):
    body = b'[{"value":1}, {"value":' + constant
    body += b'},' if truncated else b'}]'
    assert json_validation(body, truncated=truncated).status == "unconfirmed"


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
    (200, "text/html", b'<html><form><input type="password"></form></html>', "restricted"),
    (200, "text/html", b"<html>CAPTCHA</html>", "unconfirmed"),
    (200, "text/csv", b"<html>Log in</html>", "unconfirmed"),
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
    (403, "text/html", b"", "unconfirmed"),
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


@pytest.mark.parametrize("code", [200, 403])
@pytest.mark.parametrize("mime,body,status,reason", [
    ("text/html", b'<form><input type="password"></form>', "restricted", "login form"),
    ("text/csv", b'<html><form><input type=password></form></html>',
     "restricted", "login form"),
    ("text/html", b'<form><input type="password">CAPTCHA</form>',
     "restricted", "login form"),
    ("text/html", b"<html>Authentication <strong>is required</strong></html>",
     "restricted", "explicitly requires"),
    ("text/html", b"<html>CAPTCHA</html>", "unconfirmed", "anti-bot challenge"),
    ("text/html", b"<html>Verify you are human</html>", "unconfirmed", "anti-bot challenge"),
    ("text/html", b'<html><div class="g-recaptcha"></div></html>',
     "unconfirmed", "anti-bot challenge"),
    ("text/html", b"<html>Checking your browser</html>", "unconfirmed", "anti-bot challenge"),
    ("application/json", b'{"error":"authentication required"}',
     "restricted", "explicitly requires"),
    ("application/json", b'{"error":"This resource requires authentication"}',
     "restricted", "explicitly requires"),
    ("application/json", b'{"error":{"code":"INVALID_API_KEY"}}',
     "restricted", "explicitly requires"),
    ("application/json", b'{"detail":"Authentication credentials were not provided."}',
     "restricted", "explicitly requires"),
    ("application/json", b'{"error":"Insufficient permissions"}',
     "restricted", "explicitly requires"),
    ("application/json", b'{"error":"unauthorized"}', "restricted", "explicitly requires"),
    ("application/json", b'{"error":"CAPTCHA required"}', "unconfirmed", "anti-bot challenge"),
    ("application/json", b'{"error":"CAPTCHA; authentication required"}',
     "restricted", "explicitly requires"),
])
def test_access_evidence_with_success_or_http_error(code, mime, body, status, reason):
    def probe(url, method, **kwargs):
        return HTTPProbe(url, url, code, {"content-type": mime},
                         body if method == "GET" else b"",
                         error="HTTP Error 403: Forbidden" if code == 403 else "")

    result = validate_distribution(DistributionCandidate(URL, "API", .9), probe=probe)
    assert result.status == status
    assert result.ok is False
    assert reason in result.reason


@pytest.mark.parametrize("code", [200, 403])
@pytest.mark.parametrize("body", [
    b'{"error":"Forbidden"}',
    b'{"error":"Access denied"}',
    b'{"error":"See API key documentation"}',
    b'{"error":"Bad request","data":[{"note":"authentication required"}]}',
])
def test_generic_api_errors_do_not_prove_authentication(code, body):
    result = json_validation(body, code=code)
    assert result.status == "unconfirmed"
    assert result.reason == (
        "HTTP 403 refused the check without explicit authentication or permission requirements."
        if code == 403 else "The API returned an error response."
    )


@pytest.mark.parametrize("code", [200, 403])
@pytest.mark.parametrize("body", [
    b'<html><a href="/login">Log in</a><p>Documentation</p></html>',
    b'<html><script>const error = "authentication required CAPTCHA";</script></html>',
    b'<html><style>.captcha { display: none; }</style><p>Documentation</p></html>',
    b'<html><pre>&lt;input type="password"&gt;</pre></html>',
])
def test_html_mentions_are_not_access_evidence(code, body):
    result = validate_distribution(
        DistributionCandidate(URL, "API", .9),
        probe=lambda url, method, **kw: HTTPProbe(
            url, url, code, {"content-type": "text/html"}, body if method == "GET" else b"",
        ),
    )
    assert result.status == "unconfirmed"
    assert result.reason == (
        "HTTP 403 refused the check without explicit authentication or permission requirements."
        if code == 403 else "HTML was returned instead of data."
    )


@pytest.mark.parametrize("mime,body", [
    ("text/html", b""),
    ("text/plain", b"Forbidden"),
    ("text/csv", b"country,value\nCH,1\n"),
    ("application/json", b'[{"value":1}]'),
    ("application/json", b'{"data":[{"value":1}]}'),
    ("application/json", b'{"data":[{"note":"authentication required"}]}'),
    ("application/json", b'{"error":"authentication req'),
])
def test_bare_403_never_confirms_data_or_restriction(mime, body):
    calls = []

    def probe(url, method, **kwargs):
        calls.append((method, kwargs))
        return HTTPProbe(url, url, 403, {"content-type": mime}, body,
                         error="HTTP Error 403: Forbidden")

    result = validate_distribution(
        DistributionCandidate(URL, "API", .9), timeout=2, max_sample_bytes=128, probe=probe,
    )
    assert result.status == "unconfirmed"
    assert result.ok is False
    assert result.reason == (
        "HTTP 403 refused the check without explicit authentication or permission requirements."
    )
    assert calls == [
        ("HEAD", {"timeout": 2, "max_bytes": 0}),
        ("GET", {"timeout": 2, "max_bytes": 128, "headers": {"Range": "bytes=0-127"}}),
    ]


def test_403_authentication_challenge_header_is_explicit_evidence():
    result = json_validation(
        b"", code=403, extra_headers={"www-authenticate": 'Bearer realm="api"'},
    )
    assert result.status == "restricted"
    assert result.reason == "The server explicitly requests authentication."


def test_403_plain_text_can_explain_an_explicit_restriction():
    result = validate_distribution(
        DistributionCandidate(URL, "API", .9),
        probe=lambda url, **kw: HTTPProbe(
            url, url, 403, {"content-type": "text/plain"}, b"Permission is required.",
            error="HTTP Error 403: Forbidden",
        ),
    )
    assert result.status == "restricted"


def test_head_403_followed_by_valid_get_confirms_data():
    calls = []

    def probe(url, method, **kwargs):
        calls.append(method)
        if method == "HEAD":
            return HTTPProbe(url, url, 403, error="HTTP Error 403: Forbidden")
        return HTTPProbe(url, url, 200, {"content-type": "text/csv"}, b"country,value\nCH,1\n")

    result = validate_distribution(DistributionCandidate(URL, "CSV", .9), probe=probe)
    assert result.status == "available"
    assert calls == ["HEAD", "GET"]


def test_authentication_mentions_in_json_data_remain_available():
    result = json_validation(b'{"data":[{"note":"authentication required; CAPTCHA"}]}')
    assert result.status == "available"


@pytest.mark.parametrize("code", [200, 403])
def test_malformed_html_remains_unconfirmed(code):
    result = validate_distribution(
        DistributionCandidate(URL, "API", .9),
        probe=lambda url, **kw: HTTPProbe(
            url, url, code, {"content-type": "text/html"}, b"<html><![invalid[ test ]]></html>",
        ),
    )
    assert result.status == "unconfirmed"
    assert result.reason == "The HTML response could not be interpreted to confirm data access."


@pytest.mark.parametrize("code,status", [(401, "restricted"), (404, "unavailable"),
                                       (410, "unavailable")])
def test_definitive_http_status_takes_precedence_over_body(code, status):
    calls = []

    def probe(url, method, **kwargs):
        calls.append(method)
        return HTTPProbe(url, url, code, {"content-type": "text/html"},
                         b'<form><input type="password">CAPTCHA</form>')

    result = validate_distribution(DistributionCandidate(URL, "API", .9), probe=probe)
    assert result.status == status
    assert calls == ["HEAD"]


def test_http_error_body_read_remains_bounded(monkeypatch):
    reads = []

    class Body(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def open_url(*args, **kwargs):
        raise HTTPError(URL, 403, "Forbidden", {"content-type": "text/html"},
                        Body(b"<html>CAPTCHA</html>" + b" " * 1000))

    monkeypatch.setattr("collector.validation.downloads.open_public_http_url", open_url)
    result = validate_distribution(DistributionCandidate(URL, "API", .9), max_sample_bytes=64)
    assert result.status == "unconfirmed"
    assert result.reason == "An anti-bot challenge prevented verification of data access."
    assert reads == [64]


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


@pytest.mark.parametrize("code,body,status", [
    (401, b"", "restricted"),
    (403, b"", "unconfirmed"),
    (403, b"<html>Authentication required</html>", "restricted"),
    (200, b"<html>CAPTCHA</html>", "unconfirmed"),
    (404, b"", "unavailable"),
    (410, b"", "unavailable"),
])
def test_failed_validations_survive_dataset_rejection(code, body, status):
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
            item, probe=lambda url, **kw: HTTPProbe(
                url, url, code, {"content-type": "text/html"}, body,
            )),
    )
    assert result.datasets == []
    assert result.report.invalid_distribution_count == 1
    assert result.report.validation_failures[0].status == status
    assert result.report.validation_failures[0].reason
