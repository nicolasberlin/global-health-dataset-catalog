"""Exercise the standalone client against HTTP without providers or a database."""

import http.client
import json
import os
import socket
import ssl
import threading
import time
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

import scripts.test_api as api_cli
from scripts.test_api import (
    APIError,
    Client,
    _HTTPConnection,
    _HTTPSConnection,
    _HTTPSHandler,
    main,
    parse_args,
)

SEARCH_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def isolated_client_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(api_cli, "DEFAULT_ENV_FILE", tmp_path / ".env.api-client")
    monkeypatch.setattr(api_cli, "STARTUP_WAIT_SECONDS", 0)
    for key in api_cli.CLIENT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def api_server():
    calls = []
    state = {"polls": 0, "reject": False, "overrides": {}, "stop": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append((self.command, self.path, dict(self.headers), body))
            path = self.path.removeprefix("/api")
            status, headers = 200, {}
            if path in {"/health", "/ready"}:
                payload = {"status": "ok"}
            elif path == "/session":
                status, payload = 204, None
                headers["Set-Cookie"] = "visitor=test-owner; Path=/; HttpOnly"
            elif path == "/collector/searches" or path.endswith("/retry"):
                if state["reject"]:
                    status, payload = 429, {"detail": self.headers.get("Authorization")}
                    headers["Retry-After"] = "60"
                else:
                    status, payload = 202, {
                        "search_id": SEARCH_ID, "attempt": 2 if path.endswith("/retry") else 1,
                        "execution_status": "queued",
                        "progress_url": f"/api/collector/searches/{SEARCH_ID}/progress",
                    }
                if state.pop("lose_command_once", False):
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
            elif path.endswith("/progress") or path.endswith("/latest"):
                state["polls"] += 1
                active = state["polls"] == 1
                payload = {
                    "search_id": SEARCH_ID,
                    "execution_status": "running" if active else "finished",
                    "polling_required": active,
                    "outcome": None if active else "results",
                    "dataset_ids": list(range(1, 102)) if not active else [],
                }
                payload.update(state.get("snapshot", {}))
            elif path.endswith("/diagnostics"):
                payload = {
                    "schema_version": "1.0", "document_type": "search_diagnostic_trace",
                    "context": {"search_id": SEARCH_ID},
                    "summary": {
                        "search_id": SEARCH_ID, "execution_status": "finished",
                        "polling_required": False, "outcome": "results", "dataset_ids": [],
                    },
                    "collections": [],
                }
            elif path.startswith("/collector/collected-datasets/by-id?"):
                ids = parse_qs(urlsplit(path).query)["ids"]
                payload = {"items": [{"id": int(item)} for item in ids]}
                if state.get("bad_datasets"):
                    payload["items"] = [{"id": 99999}]
            else:
                status, payload = 404, {"detail": "Not found"}
            override = state["overrides"].get(path, {})
            status = override.get("status", status)
            headers.update(override.get("headers", {}))
            payload = override.get("payload", payload)
            if override.get("slow_headers"):
                try:
                    for byte in b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if state["stop"].wait(0.02):
                            return
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            raw = override.get("raw", json.dumps(payload).encode() if payload is not None else b"")
            try:
                if override.get("slow_body"):
                    for byte in raw:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if state["stop"].wait(0.02):
                            return
                else:
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True,
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api", calls, state
    finally:
        state["stop"].set()
        server.shutdown()
        server.server_close()
        thread.join()


def arguments(url, tmp_path, *extra):
    return ["--base-url", url, "--auth", "local", "--output", str(tmp_path / "report.json"),
            "--interval", "0.001", *extra]


def test_public_pipeline_and_cookie_resume(api_server, tmp_path):
    url, calls, _ = api_server
    output, cookies = tmp_path / "report.json", tmp_path / "cookies"
    common = ["--base-url", url, "--auth", "public", "--origin", "https://catalog.test",
              "--cookie-file", str(cookies), "--output", str(output), "--interval", "0.001"]
    assert main(["--query", "malaria", *common]) == 0
    report = json.loads(output.read_text())
    assert report["progress"]["outcome"] == "results"
    assert report["diagnostics"]["context"]["search_id"] == SEARCH_ID
    assert len(report["datasets"]) == 101
    dataset_calls = [call for call in calls if "by-id?" in call[1]]
    assert [call[1].count("ids=") for call in dataset_calls] == [100, 1]
    command = next(call for call in calls if call[1] == "/api/collector/searches")
    assert command[2]["Cookie"] == "visitor=test-owner"
    assert command[2]["Idempotency-Key"] == report["idempotency_key"]
    assert json.loads(command[3]) == {"query": "malaria"}
    assert cookies.stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o600
    assert "test-owner" not in output.read_text()
    assert main(["--latest", *common]) == 0
    bootstraps = [call for call in calls if call[1] == "/api/session"]
    assert bootstraps[-1][2]["Cookie"] == "visitor=test-owner"


def test_quota_error_preserves_command_key_without_secrets(
    api_server, tmp_path, monkeypatch, capsys,
):
    url, calls, state = api_server
    state["reject"] = True
    monkeypatch.setenv("API_TOKEN", "private-test-token")
    output = tmp_path / "report.json"
    assert main(["--query", "malaria", "--base-url", url, "--key", "saved-key",
                 "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["idempotency_key"] == "saved-key"
    assert report["command_state"] == "rejected"
    assert report["http_status"] == 429
    assert report["retry_after"] == "60"
    assert "Retry-After=60" in report["error"]
    assert "private-test-token" not in output.read_text() + str(capsys.readouterr())
    assert len([call for call in calls if call[0] == "POST"]) == 1


def test_no_wait_saves_id_without_polling(api_server, tmp_path):
    url, calls, _ = api_server
    assert main(["--query", "malaria", *arguments(url, tmp_path), "--no-wait"]) == 0
    assert json.loads((tmp_path / "report.json").read_text())["search_id"] == SEARCH_ID
    assert not any("/progress" in call[1] for call in calls)


def test_lost_command_response_keeps_key_for_explicit_replay(api_server, tmp_path):
    url, calls, state = api_server
    state["lose_command_once"] = True
    common = ["--query", "malaria", *arguments(url, tmp_path), "--no-wait"]
    assert main(common) == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["command_state"] == "uncertain"
    assert main([*common, "--key", report["idempotency_key"]]) == 0
    commands = [call for call in calls if call[1] == "/api/collector/searches"]
    assert len(commands) == 2
    assert commands[0][2]["Idempotency-Key"] == commands[1][2]["Idempotency-Key"]
    assert commands[0][3] == commands[1][3]


def test_retry_is_explicit_and_preserves_search_identity(api_server, tmp_path):
    url, calls, _ = api_server
    assert main(["--search-id", SEARCH_ID, "--retry", "--key", "retry-key",
                 *arguments(url, tmp_path), "--no-wait"]) == 0
    command = next(call for call in calls if call[1].endswith("/retry"))
    assert command[2]["Idempotency-Key"] == "retry-key"
    assert json.loads(command[3]) == {}
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["command_action"] == "retry"
    assert report["command"]["attempt"] == 2


def test_resume_does_not_require_workers_ready(api_server, tmp_path):
    url, calls, state = api_server
    state["overrides"]["/ready"] = {"status": 503}
    assert main(["--search-id", SEARCH_ID, *arguments(url, tmp_path)]) == 0
    assert not any(call[1].endswith("/ready") for call in calls)
    assert not any(call[0] == "POST" for call in calls)


@pytest.mark.parametrize("snapshot", [
    {"search_id": OTHER_ID}, {"execution_status": "unknown"}, {"polling_required": "false"},
    {"dataset_ids": [True]}, {"dataset_ids": [-1]}, {"dataset_ids": ["1"]},
    {"outcome": "results"}, {"execution_status": "finished", "polling_required": True},
])
def test_invalid_progress_is_rejected_before_dataset_fetch(api_server, tmp_path, snapshot):
    url, calls, state = api_server
    state["snapshot"] = snapshot
    assert main(["--search-id", SEARCH_ID, *arguments(url, tmp_path)]) == 1
    assert not any("by-id?" in call[1] for call in calls)


def test_datasets_must_match_progress_ids(api_server, tmp_path):
    url, _, state = api_server
    state["bad_datasets"] = True
    assert main(["--search-id", SEARCH_ID, *arguments(url, tmp_path)]) == 1
    assert "requested IDs" in json.loads((tmp_path / "report.json").read_text())["error"]


@pytest.mark.parametrize(
    "execution,outcome", [("finished", "incomplete"), ("failed", "incomplete")],
)
def test_incomplete_and_failed_are_distinct_from_client_errors(
    api_server, tmp_path, execution, outcome,
):
    url, _, state = api_server
    state["snapshot"] = {
        "execution_status": execution, "outcome": outcome, "polling_required": False,
    }
    assert main(["--search-id", SEARCH_ID, *arguments(url, tmp_path)]) == 2
    report = json.loads((tmp_path / "report.json").read_text())
    assert "diagnostics" in report
    assert "error" not in report


@pytest.mark.parametrize("part", ["slow_headers", "slow_body"])
def test_absolute_http_deadline_stops_trickled_responses(api_server, part):
    url, _, state = api_server
    state["overrides"]["/health"] = {part: True, "raw": b'{"status":"ok"}'}
    started = time.monotonic()
    with pytest.raises(APIError, match="HTTP deadline"):
        Client(url, timeout=0.08).request("GET", "/health")
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize("tcp_elapsed", [29, 30])
def test_tls_uses_only_the_budget_remaining_after_tcp(monkeypatch, tcp_elapsed):
    now, handshakes = [0], []

    class Socket:
        timeout = None
        closed = False

        def settimeout(self, value):
            self.timeout = value

        def close(self):
            self.closed = True

    sock = Socket()

    def connect(connection):
        connection.sock = sock
        now[0] += tcp_elapsed

    class Context:
        def wrap_socket(self, connected, *, server_hostname):
            handshakes.append((connected.timeout, server_hostname))
            now[0] += 0.5
            return connected

    monkeypatch.setattr("scripts.test_api.time.monotonic", lambda: now[0])
    monkeypatch.setattr(http.client.HTTPConnection, "connect", connect)
    connection = _HTTPSConnection("catalog.test", timeout=30, deadline=30)
    connection._context = Context()
    if tcp_elapsed == 30:
        with pytest.raises(TimeoutError):
            connection.connect()
        assert handshakes == []
        assert sock.closed
    else:
        connection.connect()
        assert handshakes == [(1, "catalog.test")]
        assert sock.timeout == 0.5


def test_https_handler_uses_the_ssl_context_for_hostname_checks(monkeypatch):
    request = Request("https://catalog.test/health")
    request.deadline = time.monotonic() + 30
    handler = _HTTPSHandler()

    def open_connection(factory, req, **options):
        assert "check_hostname" not in options
        connection = factory(req.host, timeout=30, **options)
        assert connection._context.check_hostname
        assert connection._context.verify_mode == ssl.CERT_REQUIRED
        return connection

    monkeypatch.setattr(handler, "do_open", open_connection)
    handler.https_open(request)


@pytest.mark.parametrize("first_elapsed", [29, 30])
def test_each_dns_address_uses_remaining_budget(monkeypatch, first_elapsed):
    now, sockets, timeouts = [0], [], []

    class Socket:
        closed = False

        def __init__(self, *args):
            sockets.append(self)

        def settimeout(self, value):
            self.timeout = value

        def connect(self, address):
            timeouts.append(self.timeout)
            if len(sockets) == 1:
                now[0] += first_elapsed
                raise OSError("first address failed")

        def close(self):
            self.closed = True

    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, 80))
                 for host in ("192.0.2.1", "192.0.2.2")]
    monkeypatch.setattr("scripts.test_api.time.monotonic", lambda: now[0])
    monkeypatch.setattr("scripts.test_api.socket.getaddrinfo", lambda *args: addresses)
    monkeypatch.setattr("scripts.test_api.socket.socket", Socket)
    connection = _HTTPConnection("catalog.test", deadline=30, timeout=30)
    if first_elapsed == 30:
        with pytest.raises(TimeoutError):
            connection._create_connection(("catalog.test", 80), 30)
        assert timeouts == [30]
        assert len(sockets) == 1
    else:
        connection._create_connection(("catalog.test", 80), 30)
        assert timeouts == [30, 1]
    assert sockets[0].closed


def test_expired_dns_budget_prevents_any_connection(monkeypatch):
    now = [0]

    def resolve(*args):
        now[0] = 31
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.1", 80))]

    def unexpected_socket(*args):
        pytest.fail("DNS exhausted the budget; no socket may be created")

    monkeypatch.setattr("scripts.test_api.time.monotonic", lambda: now[0])
    monkeypatch.setattr("scripts.test_api.socket.getaddrinfo", resolve)
    monkeypatch.setattr("scripts.test_api.socket.socket", unexpected_socket)
    connection = _HTTPConnection("catalog.test", deadline=30, timeout=30)
    with pytest.raises(TimeoutError):
        connection._create_connection(("catalog.test", 80), 30)


def test_json_response_size_is_bounded(api_server, monkeypatch):
    url, _, state = api_server
    monkeypatch.setattr("scripts.test_api.MAX_RESPONSE_BYTES", 64)
    state["overrides"]["/health"] = {"raw": b"x" * 65}
    with pytest.raises(APIError, match="too large"):
        Client(url).request("GET", "/health")


@pytest.mark.parametrize("raw", [b"not json", b'{"v": NaN}', b"[" * 2000 + b"]" * 2000])
def test_malformed_json_is_controlled(api_server, raw):
    url, _, state = api_server
    state["overrides"]["/health"] = {"raw": raw}
    with pytest.raises(APIError, match="valid JSON"):
        Client(url).request("GET", "/health")


def test_redirect_is_not_followed_and_error_body_is_not_exposed(api_server, monkeypatch):
    url, calls, state = api_server
    state["overrides"]["/health"] = {
        "status": 302, "headers": {"Location": url + "/receiver"},
        "payload": {"secret": "private-test-token"},
    }
    with pytest.raises(APIError, match="HTTP 302") as error:
        Client(url, token="private-test-token").request("GET", "/health")
    assert len(calls) == 1
    assert "private-test-token" not in str(error.value)


def test_report_redacts_credentials_echoed_in_success(api_server, tmp_path, monkeypatch):
    url, _, state = api_server
    monkeypatch.setenv("API_TOKEN", "private-test-token")
    state["overrides"]["/health"] = {
        "payload": {"status": "ok", "echo": "private-test-token", "private-test-token": True},
    }
    assert main(["--query", "malaria", "--no-wait", "--base-url", url,
                 "--output", str(tmp_path / "report.json")]) == 0
    assert "private-test-token" not in (tmp_path / "report.json").read_text()


@pytest.mark.parametrize("change", [
    {"search_id": "bad"}, {"attempt": True}, {"execution_status": "bad"},
    {"progress_url": "https://other.example/receive"},
])
def test_invalid_command_ack_remains_uncertain(api_server, tmp_path, change):
    url, calls, state = api_server
    payload = {
        "search_id": SEARCH_ID, "attempt": 1, "execution_status": "queued",
        "progress_url": f"/collector/searches/{SEARCH_ID}/progress", **change,
    }
    state["overrides"]["/collector/searches"] = {"payload": payload}
    assert main(["--query", "malaria", *arguments(url, tmp_path), "--no-wait"]) == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["command_state"] == "uncertain"
    assert report["idempotency_key"]
    assert not any("/progress" in call[1] for call in calls)


def test_unavailable_workers_prevent_admission(api_server, tmp_path):
    url, calls, state = api_server
    state["overrides"]["/ready"] = {"status": 503, "payload": {"status": "unavailable"}}
    assert main(["--query", "malaria", *arguments(url, tmp_path)]) == 1
    assert not any(call[0] == "POST" for call in calls)


def test_diagnostics_of_another_search_are_rejected(api_server, tmp_path):
    url, _, state = api_server
    state["overrides"][f"/collector/searches/{SEARCH_ID}/diagnostics"] = {
        "payload": {"schema_version": "1.0", "document_type": "search_diagnostic_trace",
                    "context": {"search_id": OTHER_ID}},
    }
    assert main(["--search-id", SEARCH_ID, *arguments(url, tmp_path)]) == 1


def test_http_error_stream_is_closed_without_reading_body(monkeypatch):
    client = Client("http://localhost")
    body = BytesIO(b"untrusted-secret")
    error = HTTPError("http://localhost/health", 500, "error", Message(), body)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(client.opener, "open", fail)
    with pytest.raises(APIError, match="HTTP 500"):
        client.request("GET", "/health")
    assert body.closed


def test_chunked_http_json_uses_the_same_deadline_reader(api_server):
    url, _, state = api_server
    state["overrides"]["/health"] = {
        "headers": {"Transfer-Encoding": "chunked"},
        "raw": b'7\r\n{"v":1}\r\n0\r\n\r\n',
    }
    assert Client(url).request("GET", "/health") == {"v": 1}


def test_output_symlinks_and_hardlinked_cookie_report_are_rejected(tmp_path):
    original = tmp_path / "original"
    original.write_text("untouched")
    target = tmp_path / "report"
    target.symlink_to(original)
    with pytest.raises(SystemExit):
        parse_args(["--query", "x", "--auth", "local", "--output", str(target)])
    target.unlink()
    os.link(original, target)
    with pytest.raises(SystemExit):
        parse_args(["--query", "x", "--auth", "local", "--output", str(target),
                    "--cookie-file", str(original)])
    assert original.read_text() == "untouched"


@pytest.mark.parametrize("extra", [
    ["--http-timeout", "nan"], ["--timeout", "inf"], ["--interval", "0"],
    ["--base-url", "http://user:secret@localhost"], ["--base-url", "http://localhost:bad"],
    ["--base-url", "http://localhost/\nsecret"], ["--retry"],
    ["--base-url", "http://[invalid"],
])
def test_invalid_options_fail_before_any_request(extra):
    with pytest.raises(SystemExit):
        parse_args(["--query", "x", "--auth", "local", *extra])


def test_default_config_runs_without_exports_from_another_directory(
    api_server, tmp_path, monkeypatch,
):
    url, calls, _ = api_server
    api_cli.DEFAULT_ENV_FILE.write_text(
        f'API_BASE_URL={url}\nAPI_TOKEN="private-file-token" # backend token\n',
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    output = tmp_path / "report.json"
    assert main(["--query", "pneumonia", "--no-wait", "--output", str(output)]) == 0
    command = next(call for call in calls if call[0] == "POST")
    assert command[2]["Authorization"] == "Bearer private-file-token"
    assert "private-file-token" not in output.read_text()


def test_config_precedence_and_explicit_file(tmp_path, monkeypatch):
    config = tmp_path / "custom.env"
    config.write_text("API_BASE_URL=http://file.test\nAPI_TOKEN=file-token\n", encoding="utf-8")
    monkeypatch.setenv("API_BASE_URL", "http://environment.test")
    monkeypatch.setenv("API_TOKEN", "environment-token")
    common = ["--env-file", str(config), "--query", "pneumonia"]
    args = parse_args(common)
    assert args.base_url == "http://environment.test"
    assert args.token == "environment-token"
    args = parse_args([*common, "--base-url", "http://command.test"])
    assert args.base_url == "http://command.test"


@pytest.mark.parametrize("content", [
    "API_TOKEN='unclosed-secret", "API_TOKEN=secret one", "API_TOKNE=secret",
    "API_TOKEN=secret\nAPI_TOKEN=duplicate", "API_TEST_AUTH=secret",
])
def test_invalid_config_is_actionable_without_echoing_secrets(content, capsys):
    api_cli.DEFAULT_ENV_FILE.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit):
        parse_args(["--query", "pneumonia"])
    assert "secret" not in capsys.readouterr().err


def test_explicit_missing_file_and_missing_token_have_clear_errors(tmp_path, capsys):
    with pytest.raises(SystemExit):
        parse_args(["--query", "pneumonia", "--env-file", str(tmp_path / "absent")])
    assert "could not be found" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parse_args(["--query", "pneumonia"])
    assert ".env.api-client.example" in capsys.readouterr().err


def test_startup_waits_for_workers_without_submitting_work(monkeypatch):
    calls = []

    class StartingAPI:
        def request(self, method, path, **kwargs):
            calls.append((method, path))
            if path == "/ready" and calls.count((method, path)) == 1:
                raise APIError("HTTP 503", status=503)
            return {"status": "ok"}

    monkeypatch.setattr(api_cli, "STARTUP_WAIT_SECONDS", 60)
    monkeypatch.setattr(api_cli.time, "sleep", lambda seconds: None)
    assert api_cli.startup_checks(StartingAPI(), processing=True) == {
        "health": {"status": "ok"}, "ready": {"status": "ok"},
    }
    assert calls == [("GET", "/health"), ("GET", "/ready")] * 2


def test_startup_does_not_retry_authentication_errors(monkeypatch):
    class UnauthorizedAPI:
        def request(self, method, path, **kwargs):
            raise APIError("HTTP 401", status=401)

    monkeypatch.setattr(api_cli, "STARTUP_WAIT_SECONDS", 60)
    with pytest.raises(APIError, match="HTTP 401"):
        api_cli.startup_checks(UnauthorizedAPI(), processing=True)


def test_startup_expiry_does_not_claim_a_search_is_running(monkeypatch):
    now = [0]
    calls = []

    class UnavailableAPI:
        def request(self, method, path, **kwargs):
            calls.append((method, path))
            now[0] = 60
            raise APIError("Tracking timed out; server processing continues.")

    monkeypatch.setattr(api_cli, "STARTUP_WAIT_SECONDS", 60)
    monkeypatch.setattr(api_cli.time, "monotonic", lambda: now[0])
    with pytest.raises(APIError) as error:
        api_cli.startup_checks(UnavailableAPI(), processing=True)
    message = str(error.value)
    assert "No search command was submitted" in message
    assert "docker compose" in message
    assert "server processing continues" not in message
    assert calls == [("GET", "/health")]


def test_default_api_files_stay_in_their_own_area_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = parse_args(["--query", "pneumonia", "--auth", "local"])
    area = api_cli.PROJECT_ROOT / "research" / "api"
    assert args.output == area / "outputs" / "api-test.json"
    assert args.cookie_file == area / "sessions" / "api.cookies"
    assert args.output.is_absolute() and args.cookie_file.is_absolute()
