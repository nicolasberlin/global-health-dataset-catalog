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

import scripts.api_client as api_cli
from scripts.api_client import (
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
    monkeypatch.setattr(api_cli, "POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(api_cli, "DEFAULT_OUTPUT_FILE", tmp_path / "report.json")
    monkeypatch.setattr(api_cli, "DEFAULT_COOKIE_FILE", tmp_path / "cookies")
    monkeypatch.setattr(api_cli, "DEFAULT_PENDING_FILE", tmp_path / "pending-search.json")
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
                headers["Set-Cookie"] = (
                    f"visitor={state.get('visitor', 'test-owner')}; Path=/; HttpOnly"
                )
            elif path == "/collector/searches" or path.endswith("/retry"):
                if state["reject"]:
                    status, payload = 429, {"detail": self.headers.get("Cookie")}
                    headers["Retry-After"] = "60"
                else:
                    status, payload = (
                        202,
                        {
                            "search_id": SEARCH_ID,
                            "attempt": 2 if path.endswith("/retry") else 1,
                            "execution_status": "queued",
                            "progress_url": f"/api/collector/searches/{SEARCH_ID}/progress",
                        },
                    )
                if state.pop("lose_command_once", False):
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
            elif path.endswith("/latest"):
                payload = {
                    "search_id": SEARCH_ID,
                    "execution_status": "running",
                    "polling_required": True,
                    "outcome": None,
                    "dataset_ids": [],
                }
            elif path.endswith("/progress"):
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
                    "schema_version": "1.0",
                    "document_type": "search_diagnostic_trace",
                    "context": {"search_id": SEARCH_ID},
                    "summary": {
                        "search_id": SEARCH_ID,
                        "execution_status": "finished",
                        "polling_required": False,
                        "outcome": "results",
                        "dataset_ids": [],
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
        target=server.serve_forever,
        kwargs={"poll_interval": 0.02},
        daemon=True,
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api", calls, state
    finally:
        state["stop"].set()
        server.shutdown()
        server.server_close()
        thread.join()


def configure(url, *, mode="local", origin=""):
    api_cli.DEFAULT_ENV_FILE.write_text(
        f"API_BASE_URL={url}\nAPI_CLIENT_MODE={mode}\nAPI_PUBLIC_ORIGIN={origin}\n"
    )


def arguments(url, tmp_path, *extra):
    configure(url)
    return list(extra)


def test_public_pipeline_and_cookie_resume(api_server, tmp_path):
    url, calls, _ = api_server
    output, cookies = tmp_path / "report.json", tmp_path / "cookies"
    configure(url, mode="public", origin="https://catalog.test")
    common = []
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
    api_server,
    tmp_path,
    monkeypatch,
    capsys,
):
    url, calls, state = api_server
    state["reject"] = True
    output = tmp_path / "report.json"
    assert (
        main(["--query", "malaria", *arguments(url, tmp_path)])
        == 1
    )
    report = json.loads(output.read_text())
    assert report["idempotency_key"]
    assert not api_cli.DEFAULT_PENDING_FILE.exists()
    assert report["command_state"] == "rejected"
    assert report["http_status"] == 429
    assert report["retry_after"] == "60"
    assert "Retry-After=60" in report["error"]
    assert "private-test-token" not in output.read_text() + str(capsys.readouterr())
    assert len([call for call in calls if call[0] == "POST"]) == 1


def test_lost_command_response_reuses_saved_key_even_after_latest(api_server, tmp_path):
    url, calls, state = api_server
    state["lose_command_once"] = True
    common = ["--query", "malaria", *arguments(url, tmp_path)]
    assert main(common) == 1
    report = json.loads(api_cli.DEFAULT_OUTPUT_FILE.read_text())
    assert report["command_state"] == "uncertain"
    pending = api_cli.DEFAULT_PENDING_FILE.read_bytes()
    assert api_cli.DEFAULT_PENDING_FILE.stat().st_mode & 0o777 == 0o600
    assert main(["--latest"]) == 0
    assert api_cli.DEFAULT_PENDING_FILE.read_bytes() == pending
    assert main(common) == 0
    commands = [call for call in calls if call[1] == "/api/collector/searches"]
    assert len(commands) == 2
    assert commands[0][2]["Idempotency-Key"] == commands[1][2]["Idempotency-Key"]
    assert commands[0][3] == commands[1][3]
    assert not api_cli.DEFAULT_PENDING_FILE.exists()


def test_resume_does_not_require_workers_ready(api_server, tmp_path):
    url, calls, state = api_server
    state["overrides"]["/ready"] = {"status": 503}
    assert main(["--latest", *arguments(url, tmp_path)]) == 0
    assert not any(call[1].endswith("/ready") for call in calls)
    assert not any(call[0] == "POST" for call in calls)


def test_confirmed_repeated_query_uses_a_new_key(api_server):
    url, calls, _ = api_server
    configure(url)
    assert main(["--query", "malaria"]) == 0
    assert main(["--query", "malaria"]) == 0
    commands = [call for call in calls if call[1] == "/api/collector/searches"]
    assert len(commands) == 2
    assert commands[0][2]["Idempotency-Key"] != commands[1][2]["Idempotency-Key"]


@pytest.mark.parametrize("change", ["query", "server", "session", "renewed_session"])
def test_uncertain_search_cannot_be_replayed_with_another_context(api_server, change):
    url, calls, state = api_server
    configure(url, mode="public", origin="https://catalog.test")
    state["lose_command_once"] = True
    assert main(["--query", "malaria"]) == 1
    saved = api_cli.DEFAULT_PENDING_FILE.read_bytes()
    searches = len([c for c in calls if c[1] == "/api/collector/searches"])
    query = "malaria"
    if change == "query":
        query = "diabetes"
    elif change == "server":
        configure(url.replace("127.0.0.1", "localhost"), mode="public", origin="https://catalog.test")
    elif change == "session":
        api_cli.DEFAULT_COOKIE_FILE.unlink()
    else:
        state["visitor"] = "another-session"
    assert main(["--query", query]) == 1
    assert api_cli.DEFAULT_PENDING_FILE.read_bytes() == saved
    assert len([c for c in calls if c[1] == "/api/collector/searches"]) == searches
    assert "unknown acceptance" in api_cli.DEFAULT_OUTPUT_FILE.read_text()
    assert "test-owner" not in saved.decode()


@pytest.mark.parametrize("status", [408, 499, 500, 503])
def test_uncertain_http_errors_preserve_the_key_for_a_later_replay(api_server, status):
    url, calls, state = api_server
    configure(url)
    state["overrides"]["/collector/searches"] = {"status": status}
    assert main(["--query", "malaria"]) == 1
    pending = json.loads(api_cli.DEFAULT_PENDING_FILE.read_text())
    state["overrides"].clear()
    assert main(["--query", "malaria"]) == 0
    commands = [call for call in calls if call[1] == "/api/collector/searches"]
    assert len(commands) == 2
    assert {c[2]["Idempotency-Key"] for c in commands} == {pending["key"]}


def test_corrupt_recovery_state_is_preserved_without_submitting(api_server):
    url, calls, _ = api_server
    configure(url)
    api_cli.DEFAULT_PENDING_FILE.write_text("not-json")
    assert main(["--query", "malaria"]) == 1
    assert api_cli.DEFAULT_PENDING_FILE.read_text() == "not-json"
    assert not calls


def test_concurrent_client_cannot_overwrite_shared_state(api_server):
    url, calls, _ = api_server
    configure(url)
    api_cli.DEFAULT_OUTPUT_FILE.write_text("preserve existing report")
    with api_cli.client_lock():
        assert main(["--query", "malaria"]) == 1
    assert api_cli.DEFAULT_OUTPUT_FILE.read_text() == "preserve existing report"
    assert not calls


@pytest.mark.parametrize("phase", ["/health", "/collector/searches", "/progress"])
def test_interrupt_messages_match_what_was_submitted(api_server, monkeypatch, phase):
    url, _, _ = api_server
    configure(url)
    request = Client.request

    def interrupt(client, method, path, **options):
        if path.endswith(phase):
            raise KeyboardInterrupt
        return request(client, method, path, **options)

    monkeypatch.setattr(Client, "request", interrupt)
    assert main(["--query", "malaria"]) == 130
    report = json.loads(api_cli.DEFAULT_OUTPUT_FILE.read_text())
    if phase == "/health":
        assert "No search request was submitted" in report["error"]
        assert not api_cli.DEFAULT_PENDING_FILE.exists()
    elif phase == "/collector/searches":
        assert "Acceptance is unknown" in report["error"]
        assert api_cli.DEFAULT_PENDING_FILE.exists()
    else:
        assert "The search is not cancelled" in report["error"]
        assert report["command_state"] == "acknowledged"
        assert not api_cli.DEFAULT_PENDING_FILE.exists()


def test_tracking_timeout_resumes_latest_without_submitting_again(
    api_server, tmp_path, monkeypatch,
):
    url, calls, state = api_server
    state["snapshot"] = {
        "execution_status": "running", "polling_required": True,
        "outcome": None, "dataset_ids": [],
    }
    assert main(["--query", "malaria", "--timeout", "0.03", *arguments(url, tmp_path)]) == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["command_state"] == "acknowledged"
    assert report["search_id"] == SEARCH_ID
    assert "deadline" in report["error"]
    assert not any(call[1].endswith("/retry") for call in calls)

    state["snapshot"] = {}
    assert main(["--latest", *arguments(url, tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["search_id"] == SEARCH_ID
    assert len(report["datasets"]) == 101
    assert len([call for call in calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("snapshot", [
    {"search_id": OTHER_ID}, {"execution_status": "unknown"}, {"polling_required": "false"},
    {"dataset_ids": [True]}, {"dataset_ids": [-1]}, {"dataset_ids": ["1"]},
    {"outcome": "results"}, {"execution_status": "finished", "polling_required": True},
])
def test_invalid_progress_is_rejected_before_dataset_fetch(api_server, tmp_path, snapshot):
    url, calls, state = api_server
    state["snapshot"] = snapshot
    assert main(["--latest", *arguments(url, tmp_path)]) == 1
    assert not any("by-id?" in call[1] for call in calls)


def test_datasets_must_match_progress_ids(api_server, tmp_path):
    url, _, state = api_server
    state["bad_datasets"] = True
    assert main(["--latest", *arguments(url, tmp_path)]) == 1
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
    assert main(["--latest", *arguments(url, tmp_path)]) == 2
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

    monkeypatch.setattr("scripts.api_client.time.monotonic", lambda: now[0])
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
    monkeypatch.setattr("scripts.api_client.time.monotonic", lambda: now[0])
    monkeypatch.setattr("scripts.api_client.socket.getaddrinfo", lambda *args: addresses)
    monkeypatch.setattr("scripts.api_client.socket.socket", Socket)
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

    monkeypatch.setattr("scripts.api_client.time.monotonic", lambda: now[0])
    monkeypatch.setattr("scripts.api_client.socket.getaddrinfo", resolve)
    monkeypatch.setattr("scripts.api_client.socket.socket", unexpected_socket)
    connection = _HTTPConnection("catalog.test", deadline=30, timeout=30)
    with pytest.raises(TimeoutError):
        connection._create_connection(("catalog.test", 80), 30)


def test_json_response_size_is_bounded(api_server, monkeypatch):
    url, _, state = api_server
    monkeypatch.setattr("scripts.api_client.MAX_RESPONSE_BYTES", 64)
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
        "status": 302,
        "headers": {"Location": url + "/receiver"},
        "payload": {"secret": "private-test-token"},
    }
    with pytest.raises(APIError, match="HTTP 302") as error:
        Client(url).request("GET", "/health")
    assert len(calls) == 1
    assert "private-test-token" not in str(error.value)


def test_report_redacts_session_cookies_echoed_in_success(api_server, tmp_path):
    url, _, state = api_server
    state["overrides"]["/ready"] = {
        "payload": {"status": "ok", "echo": "test-owner", "test-owner": True},
    }
    configure(url, mode="public", origin="https://catalog.test")
    assert main(["--query", "malaria"]) == 0
    assert main(["--query", "malaria"]) == 0
    assert "test-owner" not in (tmp_path / "report.json").read_text()


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
    assert main(["--query", "malaria", *arguments(url, tmp_path)]) == 1
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
    assert main(["--latest", *arguments(url, tmp_path)]) == 1


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


def test_output_symlinks_and_hardlinked_cookie_report_are_rejected(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.write_text("untouched")
    target = tmp_path / "report"
    target.symlink_to(original)
    monkeypatch.setattr(api_cli, "DEFAULT_OUTPUT_FILE", target)
    with pytest.raises(SystemExit):
        parse_args(["--query", "x"])
    target.unlink()
    os.link(original, target)
    monkeypatch.setattr(api_cli, "DEFAULT_COOKIE_FILE", original)
    with pytest.raises(SystemExit):
        parse_args(["--query", "x"])
    assert original.read_text() == "untouched"


@pytest.mark.parametrize("extra", [
    ["--search-id", SEARCH_ID], ["--latest"], ["--retry"], ["--no-wait"],
    ["--http-timeout", "30"], ["--interval", "3"], ["--key", "manual"],
    ["--base-url", "http://localhost"], ["--auth", "local"], ["--origin", "https://catalog.test"],
    ["--env-file", "other.env"], ["--cookie-file", "other.cookies"], ["--output", "other.json"],
    ["--timeout", "inf"], ["--timeout", "nan"], ["--timeout", "0"],
])
def test_invalid_or_removed_options_fail_before_any_request(extra):
    with pytest.raises(SystemExit):
        parse_args(["--query", "x", *extra])


@pytest.mark.parametrize("url", [
    "http://user:secret@localhost", "http://localhost:bad", "http://localhost/\nsecret",
    "http://[invalid", "https://remote.test", "http://localhost:0", "ftp://localhost",
])
def test_invalid_configured_address_is_rejected(url):
    configure(url)
    with pytest.raises(SystemExit):
        parse_args(["--query", "x"])


def test_default_config_runs_without_tokens_from_another_directory(
    api_server, tmp_path, monkeypatch,
):
    url, calls, _ = api_server
    configure(url)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["--query", "pneumonia"]) == 0
    assert api_cli.DEFAULT_OUTPUT_FILE.is_file()
    assert not (elsewhere / "research").exists()
    assert all("Authorization" not in call[2] for call in calls)


def test_environment_overrides_the_fixed_configuration_file(monkeypatch):
    configure("http://localhost:8001")
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8002")
    assert parse_args(["--query", "pneumonia"]).base_url == "http://localhost:8002"


@pytest.mark.parametrize("content", [
    "API_BASE_URL='unclosed-secret", "API_BASE_URL=secret one", "UNKNOWN_SETTING=secret",
    "API_CLIENT_MODE=local\nAPI_CLIENT_MODE=secret", "API_CLIENT_MODE=secret",
])
def test_invalid_config_is_actionable_without_echoing_secrets(content, capsys):
    api_cli.DEFAULT_ENV_FILE.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit):
        parse_args(["--query", "pneumonia"])
    assert "secret" not in capsys.readouterr().err


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
    assert "scripts/start_api.py" in message
    assert "server processing continues" not in message
    assert calls == [("GET", "/health")]
