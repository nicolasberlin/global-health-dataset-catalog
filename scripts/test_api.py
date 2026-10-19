"""Test the search API without the frontend (Python standard library only)."""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import shlex
import socket
import sys
import tempfile
import time
from email.utils import parsedate_to_datetime
from functools import partial
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import UUID, uuid4

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024
STATUSES = {"queued", "running", "waiting_retry", "finished", "failed"}
ACTIVE_STATUSES = {"queued", "running", "waiting_retry"}
OUTCOMES = {"results", "empty", "incomplete"}
STARTUP_WAIT_SECONDS = 60
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.api-client"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "research/api/outputs/api-test.json"
DEFAULT_COOKIE_FILE = PROJECT_ROOT / "research/api/sessions/api.cookies"
CLIENT_ENV_KEYS = {"API_BASE_URL", "API_TOKEN", "API_TEST_AUTH", "API_PUBLIC_ORIGIN"}


class APIError(RuntimeError):
    def __init__(self, message, *, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward access tokens or cookies to a redirected destination.
        return None


class _DeadlineReader:
    def __init__(self, stream, sock, deadline):
        self.stream, self.sock, self.deadline = stream, sock, deadline

    def read1(self, size=-1):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP deadline exceeded")
        self.sock.settimeout(remaining)
        return self.stream.read1(size)

    def read(self, size=-1):
        chunks, length = [], 0
        while size < 0 or length < size:
            chunk = self.read1(65536 if size < 0 else min(65536, size - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
        return b"".join(chunks)

    def readinto(self, buffer):
        # HTTPResponse.read(amt) uses readinto on Python 3.9.
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def readline(self, limit=-1):
        line = bytearray()
        while limit < 0 or len(line) < limit:
            byte = self.read1(1)
            if not byte:
                break
            line.extend(byte)
            if byte == b"\n":
                break
        return bytes(line)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _DeadlineResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, deadline, **kwargs):
        super().__init__(sock, *args, **kwargs)
        self.fp = _DeadlineReader(self.fp, sock, deadline)


class _DeadlineConnection:
    def __init__(self, *args, deadline, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadline = deadline
        self._create_connection = self._connect_with_deadline
        self.response_class = partial(_DeadlineResponse, deadline=deadline)

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP deadline exceeded")
        return remaining if self.timeout is None else min(self.timeout, remaining)

    def _connect_with_deadline(self, address, timeout, source_address=None):
        self._remaining()
        addresses = socket.getaddrinfo(*address, 0, socket.SOCK_STREAM)
        self._remaining()  # System DNS cannot be interrupted; do not connect after expiry.
        last_error = OSError("DNS returned no usable addresses")
        for family, socktype, proto, _, sockaddr in addresses:
            remaining = self._remaining()
            connection = None
            try:
                connection = socket.socket(family, socktype, proto)
                connection.settimeout(remaining)
                if source_address:
                    connection.bind(source_address)
                connection.connect(sockaddr)
                self._remaining()
                return connection
            except OSError as exc:
                last_error = exc
                if connection is not None:
                    connection.close()
                self._remaining()
            except BaseException:
                if connection is not None:
                    connection.close()
                raise
        raise last_error

    def send(self, data):
        try:
            self._remaining()
            if self.sock is None:
                self.connect()
            self.sock.settimeout(self._remaining())
            super().send(data)
            self._remaining()
        except BaseException:
            self.close()
            raise


class _HTTPConnection(_DeadlineConnection, http.client.HTTPConnection):
    pass


class _HTTPSConnection(_DeadlineConnection, http.client.HTTPSConnection):
    def connect(self):
        try:
            http.client.HTTPConnection.connect(self)
            self.sock.settimeout(self._remaining())
            self.sock = self._context.wrap_socket(
                self.sock, server_hostname=self._tunnel_host or self.host,
            )
            self.sock.settimeout(self._remaining())
        except BaseException:
            self.close()
            raise


class _HTTPHandler(HTTPHandler):
    def http_open(self, req):
        return self.do_open(partial(_HTTPConnection, deadline=req.deadline), req)


class _HTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        return self.do_open(
            partial(_HTTPSConnection, deadline=req.deadline), req,
            context=self._context,
        )


def _retry_after(value):
    if not value or len(value) > 80:
        return None
    if re.fullmatch(r"[0-9]{1,10}", value):
        return value
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _private_write(path, writer):
    path = Path(path)
    if path.is_symlink():
        raise APIError("The output file must not be a symbolic link.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.close(descriptor)
        writer(Path(temporary))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Client:
    def __init__(self, base_url, *, token="", origin="", cookie_file=None, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Accept": "application/json"}
        if token:
            if any(ord(char) < 32 or ord(char) == 127 for char in token):
                raise APIError("API_TOKEN contains invalid characters.")
            self.headers["Authorization"] = f"Bearer {token}"
        if origin:
            self.headers["Origin"] = origin
        self.cookies = MozillaCookieJar(str(cookie_file) if cookie_file else None)
        if cookie_file and cookie_file.exists():
            if cookie_file.is_symlink() or not cookie_file.is_file():
                raise APIError("The cookie file must be a regular file.")
            cookie_file.chmod(0o600)
            try:
                self.cookies.load(ignore_discard=True)
            except (OSError, ValueError) as exc:
                raise APIError("The cookie file cannot be read or is invalid.") from exc
        self.opener = build_opener(
            NoRedirect(), HTTPCookieProcessor(self.cookies), ProxyHandler({}),
            _HTTPHandler(), _HTTPSHandler(),
        )
        self.token = token

    def redact(self, value):
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        secrets = [self.token, *(cookie.value for cookie in self.cookies)]
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            text = text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]")
        return json.loads(text)

    def request(self, method, path, *, payload=None, key=None, deadline=None):
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = key
        body = None
        if payload is not None:
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            if len(body) > MAX_REQUEST_BYTES:
                raise APIError("The request exceeds the maximum allowed size.")
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        request.deadline = min(
            time.monotonic() + self.timeout, deadline if deadline is not None else math.inf,
        )
        remaining = request.deadline - time.monotonic()
        if remaining <= 0:
            raise APIError("Tracking timed out; server processing continues.")
        try:
            with self.opener.open(request, timeout=remaining) as response:
                if self.cookies.filename:
                    _private_write(
                        Path(self.cookies.filename),
                        lambda target: self.cookies.save(str(target), ignore_discard=True),
                    )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise APIError(f"Response too large: {method} {path.split('?')[0]}")
                try:
                    return json.loads(raw, parse_constant=_invalid_constant) if raw else None
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise APIError("The API did not return valid JSON.") from exc
        except HTTPError as exc:
            try:
                retry = _retry_after(exc.headers.get("Retry-After"))
                hint = f" ; Retry-After={retry}" if retry else ""
                # An error body may echo credentials supplied by the client.
                raise APIError(
                    f"HTTP {exc.code} : {method} {path.split('?')[0]}{hint}",
                    status=exc.code, retry_after=retry,
                ) from None
            finally:
                exc.close()
        except (URLError, OSError, http.client.HTTPException, ValueError) as exc:
            raise APIError(
                f"Connection failed or HTTP deadline exceeded: {method} {path.split('?')[0]}"
            ) from exc


def _invalid_constant(value):
    raise ValueError("Invalid JSON number")


def save_report(path, report):
    _private_write(
        path, lambda target: target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        ),
    )


def positive_number(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("The value must be positive and finite.")
    return number


def client_settings(path, *, required=False):
    """Read literal KEY=value settings; existing environment variables take priority."""
    settings = dict(os.environ)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        if required:
            raise APIError("The --env-file could not be found.") from None
        return settings
    except (OSError, UnicodeError):
        raise APIError("Could not read the client configuration file.") from None
    seen = set()
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        key = key.strip()
        try:
            values = shlex.split(raw, comments=True)
        except ValueError:
            values = [None, None]
        if not separator or key not in CLIENT_ENV_KEYS or key in seen or len(values) > 1:
            raise APIError(
                f"Invalid client configuration on line {number} (expected KEY=value)."
            )
        seen.add(key)
        settings.setdefault(key, values[0] if values else "")
    return settings


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="Start a new search and its server-side processing")
    source.add_argument("--search-id", type=UUID, help="Resume tracking an existing search")
    source.add_argument("--latest", action="store_true", help="Resume tracking the latest search")
    parser.add_argument(
        "--retry", action="store_true", help="Explicitly retry the selected search",
    )
    parser.add_argument("--base-url", help="API address (API_BASE_URL in .env.api-client)")
    parser.add_argument("--auth", choices=["token", "public", "local"])
    parser.add_argument("--origin", help="Exact website origin for public-session mode")
    parser.add_argument(
        "--env-file", type=Path,
        help="Private configuration; defaults to the project .env.api-client file",
    )
    parser.add_argument(
        "--cookie-file", type=Path, default=DEFAULT_COOKIE_FILE,
        help="Public session file (default: research/api/sessions/api.cookies)",
    )
    parser.add_argument("--key", help="Reuse this key when command acceptance is uncertain")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT_FILE,
        help="JSON report (default: research/api/outputs/api-test.json)",
    )
    parser.add_argument(
        "--interval", type=positive_number, default=3,
        help="Seconds between progress checks (default: 3)",
    )
    parser.add_argument(
        "--timeout", type=positive_number, default=900,
        help="Maximum tracking duration in seconds (default: 900)",
    )
    parser.add_argument(
        "--http-timeout", type=positive_number, default=30,
        help="Deadline for each HTTP request in seconds (default: 30)",
    )
    parser.add_argument(
        "--no-wait", action="store_true", help="Submit the command and exit without tracking it",
    )
    args = parser.parse_args(argv)
    try:
        settings = client_settings(
            args.env_file if args.env_file is not None else DEFAULT_ENV_FILE,
            required=args.env_file is not None,
        )
    except APIError as exc:
        parser.error(str(exc))
    args.base_url = args.base_url or settings.get("API_BASE_URL", "http://127.0.0.1:8001")
    args.auth = args.auth or settings.get("API_TEST_AUTH", "token")
    args.origin = args.origin if args.origin is not None else settings.get("API_PUBLIC_ORIGIN", "")
    args.token = settings.get("API_TOKEN", "")
    if args.auth not in {"token", "public", "local"}:
        parser.error(
            "API_TEST_AUTH must be token, public or local, matching the server configuration."
        )
    try:
        parsed = urlsplit(args.base_url)
        port = parsed.port
    except ValueError:
        parser.error("--base-url contains an invalid address or port.")
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in args.base_url)
            or port == 0):
        parser.error(
            "--base-url must be an HTTP(S) URL without credentials, query parameters or a fragment."
        )
    if args.query is not None and not 1 <= len(args.query.strip()) <= 300:
        parser.error("--query must contain between 1 and 300 characters.")
    if args.auth == "token" and not args.token:
        parser.error(
            "Missing token: for a local test, run python3 scripts/setup_api.py. "
            "For manual configuration, use .env.api-client.example "
            "and set API_TOKEN to a token authorized by your API."
        )
    if args.auth == "public":
        try:
            origin = urlsplit(args.origin)
            origin_port = origin.port
        except ValueError:
            parser.error("--origin contains an invalid address or port.")
        if (origin.scheme not in {"http", "https"} or not origin.hostname
                or origin.username or origin.password or origin.path
                or origin.query or origin.fragment or origin_port == 0
                or any(char.isspace() or ord(char) < 32 for char in args.origin)):
            parser.error(
                "--auth public requires --origin (the exact configured HTTP(S) website origin)."
            )
    if args.retry and args.query:
        parser.error("--retry requires --search-id or --latest.")
    if args.key and (not (args.query or args.retry)
                     or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", args.key)):
        parser.error("--key requires a command and 1-128 characters from A-Z a-z 0-9 . _ : -.")
    if (args.output.resolve() == args.cookie_file.resolve()
            or (args.output.exists() and args.cookie_file.exists()
                and args.output.samefile(args.cookie_file))):
        parser.error("The report and cookies must use separate files.")
    for path in (args.output, args.cookie_file):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            parser.error("The report and cookies must be regular files.")
    return args


def _uuid(value):
    if not isinstance(value, str):
        raise APIError("The API returned an invalid search ID.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise APIError("The API returned an invalid search ID.") from exc


def _snapshot(value, *, search_id=None):
    if not isinstance(value, dict):
        raise APIError("The API returned an invalid search snapshot.")
    actual_id = _uuid(value.get("search_id"))
    status, polling, outcome = (
        value.get("execution_status"), value.get("polling_required"), value.get("outcome"),
    )
    if (search_id is not None and actual_id != search_id) or status not in STATUSES:
        raise APIError("The response does not match the requested search.")
    if (type(polling) is not bool or polling != (status in ACTIVE_STATUSES)
            or (polling and outcome is not None) or (not polling and outcome not in OUTCOMES)):
        raise APIError("The API returned an inconsistent tracking state.")
    ids = value.get("dataset_ids")
    if (not isinstance(ids, list)
            or any(type(item) is not int or not 1 <= item <= 2147483647 for item in ids)):
        raise APIError("The API returned invalid dataset IDs.")
    return actual_id


def _command(value, client, *, search_id=None):
    if not isinstance(value, dict):
        raise APIError("The API returned an invalid command response.")
    actual_id = _uuid(value.get("search_id"))
    expected = f"/collector/searches/{actual_id}/progress"
    allowed = {expected, urlsplit(client.base_url).path.rstrip("/") + expected}
    if ((search_id is not None and actual_id != search_id)
            or value.get("execution_status") not in STATUSES
            or type(value.get("attempt")) is not int or value["attempt"] < 1
            or value.get("progress_url") not in allowed):
        raise APIError("The API returned an inconsistent command response.")
    return actual_id


def _datasets(value, requested):
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise APIError("The API returned an invalid dataset response.")
    received = [item.get("id") if isinstance(item, dict) else None for item in value["items"]]
    if (any(type(item) is not int for item in received)
            or len(set(received)) != len(received) or set(received) != set(requested)):
        raise APIError("The returned datasets do not match the requested IDs.")
    return value["items"]


def startup_checks(client, *, processing):
    """Allow a newly started local API to become ready before submitting work."""
    deadline = time.monotonic() + STARTUP_WAIT_SECONDS
    announced = False
    while True:
        try:
            options = {"deadline": deadline} if STARTUP_WAIT_SECONDS else {}
            checks = {"health": client.request("GET", "/health", **options)}
            if processing:
                checks["ready"] = client.request("GET", "/ready", **options)
            return checks
        except APIError as exc:
            retryable = exc.status == 503 or isinstance(
                exc.__cause__, (URLError, OSError, http.client.HTTPException),
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0 and STARTUP_WAIT_SECONDS > 0:
                raise APIError(
                    "The API is not reachable or ready after "
                    f"{STARTUP_WAIT_SECONDS} seconds. "
                    "No search command was submitted by this run. "
                    "Start the API and PostgreSQL before running the test again. "
                    "For the local Docker setup: "
                    "docker compose --env-file .env.api -f docker-compose.api.yml up -d --build",
                    status=exc.status, retry_after=exc.retry_after,
                ) from exc
            if not retryable or remaining <= 0:
                raise
            if not announced:
                print("Waiting for the API to become ready (up to 60 seconds)...", flush=True)
                announced = True
            time.sleep(min(1, remaining))


def run(args):
    report, client = {"base_url": args.base_url.rstrip("/")}, None

    def persist():
        save_report(args.output, client.redact(report) if client else report)

    try:
        client = Client(
            args.base_url, token=args.token if args.auth == "token" else "",
            origin=args.origin if args.auth == "public" else "",
            cookie_file=args.cookie_file if args.auth == "public" else None,
            timeout=args.http_timeout,
        )
        report.update(startup_checks(client, processing=bool(args.query or args.retry)))
        if args.auth == "public":
            client.request("POST", "/session")
        if args.latest:
            latest = client.request("GET", "/collector/searches/latest")
            search_id = _snapshot(latest)
        elif args.search_id:
            search_id = str(args.search_id)
        else:
            search_id = None
        if search_id:
            report["search_id"] = search_id
        if args.query or args.retry:
            key = args.key or str(uuid4())
            report.update(idempotency_key=key, command_state="uncertain")
            report["query"] = args.query if args.query else None
            report["command_action"] = "retry" if args.retry else "create"
            persist()  # Save the key and payload before sending a potentially uncertain command.
            print(f"Command key: {key}", flush=True)
            command_path = (
                f"/collector/searches/{search_id}/retry" if args.retry else "/collector/searches"
            )
            command = client.request(
                "POST", command_path,
                payload={} if args.retry else {"query": args.query}, key=key,
            )
            search_id = _command(command, client, search_id=search_id)
            report.update(command=command, command_state="acknowledged")
        report["search_id"] = search_id
        persist()
        print(f"Search ID: {search_id}", flush=True)
        if args.no_wait:
            return 0
        deadline = time.monotonic() + args.timeout
        path = f"/collector/searches/{search_id}"
        while True:
            snapshot = client.request("GET", path + "/progress", deadline=deadline)
            _snapshot(snapshot, search_id=search_id)
            report["progress"] = snapshot
            persist()
            print(
                f"Status: {snapshot['execution_status']}; "
                f"outcome: {snapshot['outcome'] or 'pending'}; "
                f"datasets: {len(snapshot['dataset_ids'])}", flush=True,
            )
            if not snapshot["polling_required"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise APIError(
                    "Tracking timed out; server processing continues. Resume with --search-id."
                )
            time.sleep(min(args.interval, remaining))
        diagnostics = client.request("GET", path + "/diagnostics", deadline=deadline)
        if (not isinstance(diagnostics, dict)
                or diagnostics.get("document_type") != "search_diagnostic_trace"
                or not isinstance(diagnostics.get("context"), dict)
                or _uuid(diagnostics["context"].get("search_id")) != search_id):
            raise APIError("The diagnostics do not match the requested search.")
        report["diagnostics"] = diagnostics
        ids = list(dict.fromkeys(snapshot["dataset_ids"]))
        report["datasets"] = []
        for offset in range(0, len(ids), 100):
            requested = ids[offset:offset + 100]
            query = urlencode([("ids", value) for value in requested])
            page = client.request(
                "GET", "/collector/collected-datasets/by-id?" + query, deadline=deadline,
            )
            report["datasets"].extend(_datasets(page, requested))
        persist()
        failed = snapshot["execution_status"] == "failed" or snapshot["outcome"] == "incomplete"
        return 2 if failed else 0
    except (APIError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        report["error"] = (
            str(exc) if isinstance(exc, APIError) else "Could not read or write the report."
        )
        if isinstance(exc, APIError):
            report["http_status"] = exc.status
            report["retry_after"] = exc.retry_after
            if exc.status is not None and report.get("command_state") == "uncertain":
                report["command_state"] = "rejected" if 400 <= exc.status < 500 else "uncertain"
        try:
            persist()
        except (OSError, APIError, ValueError, RecursionError):
            print("Could not save the report.", file=sys.stderr)
        print(f"Error: {report['error']}", file=sys.stderr)
        return 1
    finally:
        print(f"Report: {args.output}", flush=True)


def main(argv=None):
    try:
        return run(parse_args(argv))
    except KeyboardInterrupt:
        print(
            "\nTracking interrupted; server processing continues. Resume with --search-id.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    sys.exit(main())
