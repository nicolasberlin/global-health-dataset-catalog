"""Oversized uploads are rejected before JSON parsing, auth and command admission."""

from __future__ import annotations

import asyncio
import json
import socket
import time

import pytest
from app.api.middleware import (
    RequestBodyLimitMiddleware,
    configured_max_request_body_bytes,
    configured_request_body_timeout_seconds,
)
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

pytestmark = pytest.mark.anyio


async def invoke(chunks, headers=(), *, cap=8, disconnect=False):
    received = []
    calls = []
    sent = []
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    if disconnect:
        messages[-1]["more_body"] = True
        messages.append({"type": "http.disconnect"})

    async def receive():
        message = messages.pop(0)
        received.append(message)
        return message

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        calls.append(await Request(scope, receive).body())

    scope = {"type": "http", "method": "POST", "path": "/", "headers": list(headers)}
    await RequestBodyLimitMiddleware(app, max_body_bytes=cap)(scope, receive, send)
    return calls, received, sent


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"content-length", b"1")],
        [(b"content-length", b"invalid")],
        [(b"transfer-encoding", b"chunked")],
    ],
)
async def test_actual_bytes_enforced_without_a_trustworthy_length(headers):
    calls, received, sent = await invoke([b"1234", b"56789", b"never read"], headers)
    assert not calls and len(received) == 2
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"]) == {"detail": "Request body is too large."}
    assert (b"cache-control", b"no-store") in sent[0]["headers"]


async def test_declared_oversized_body_is_rejected_without_reading():
    calls, received, sent = await invoke([b""], [(b"content-length", b"9")])
    assert not calls and not received and sent[0]["status"] == 413


async def test_exact_limit_and_empty_chunks_are_replayed_without_data_loss():
    calls, received, sent = await invoke(
        [b"", b"1234", b"", b"5678"], [(b"content-length", b"00000000000000000000008")]
    )
    assert calls == [b"12345678"] and len(received) == 4 and not sent


async def test_disconnected_partial_upload_never_executes_command():
    calls, _, sent = await invoke([b"1234"], disconnect=True)
    assert not calls and not sent


async def test_non_http_connections_are_passed_through():
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["type"])

    async def unused():
        pytest.fail("Non-HTTP scope must not be read")

    await RequestBodyLimitMiddleware(app)({"type": "lifespan"}, unused, unused)
    assert calls == ["lifespan"]


@pytest.mark.parametrize("value", ["0", "-1", "1023", "1048577", "invalid"])
def test_invalid_limits_fail_configuration(monkeypatch, value):
    monkeypatch.setenv("API_MAX_REQUEST_BODY_BYTES", value)
    with pytest.raises(RuntimeError, match="API_MAX_REQUEST_BODY_BYTES"):
        configured_max_request_body_bytes()


async def test_413_precedes_json_auth_and_has_browser_cors_headers(monkeypatch):
    events = []
    original_json = Request.json

    async def observe_json(request):
        events.append("json")
        return await original_json(request)

    async def authenticate():
        events.append("auth")
        raise HTTPException(status_code=401)

    monkeypatch.setattr(Request, "json", observe_json)
    app = FastAPI()

    @app.post("/command", dependencies=[Depends(authenticate)])
    async def command(payload: dict):
        events.append("command")
        return payload

    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=32)
    app.add_middleware(
        CORSMiddleware, allow_origins=["https://health.example"], allow_credentials=True
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rejected = await client.post(
            "/command", json={"ignored": "x" * 100}, headers={"Origin": "https://health.example"}
        )
        assert rejected.status_code == 413 and not events
        assert rejected.headers["access-control-allow-origin"] == "https://health.example"
        assert rejected.headers["access-control-allow-credentials"] == "true"
        accepted = await client.post("/command", json={"query": "health"})
        assert accepted.status_code == 401 and events == ["json", "auth"]


async def test_streamed_upload_crossing_limit_is_rejected():
    events = []
    app = FastAPI()

    @app.post("/command")
    async def command(payload: dict):
        events.append(payload)
        return payload

    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=32)

    async def chunks():
        yield b'{"query":"'
        yield b"x" * 32
        yield b'"}'

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/command", content=chunks(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 413 and not events


@pytest.mark.parametrize("value", ["0", "-1", "121", "nan", "inf", "invalid"])
def test_invalid_body_timeout_fails_configuration(monkeypatch, value):
    monkeypatch.setenv("API_REQUEST_BODY_TIMEOUT_SECONDS", value)
    with pytest.raises(RuntimeError, match="API_REQUEST_BODY_TIMEOUT_SECONDS"):
        configured_request_body_timeout_seconds()


@pytest.mark.parametrize("chunks", [[], [b"x"], [b"", b"", b""], [b"x"] * 10])
@pytest.mark.parametrize("version", ["1.1", "2"])
async def test_body_deadline_is_cumulative_and_partial_body_never_reaches_app(chunks, version):
    calls, sent = [], []
    pending = list(chunks)

    async def receive():
        await asyncio.sleep(.02 if pending else 10)
        return {"type": "http.request", "body": pending.pop(0), "more_body": True}

    async def app(scope, receive, send):
        calls.append("admitted")

    scope = {"type": "http", "method": "POST", "path": "/", "headers": [],
             "http_version": version}
    started = asyncio.get_running_loop().time()
    await RequestBodyLimitMiddleware(app, body_timeout_seconds=.05)(
        scope, receive, _append_sender(sent))
    assert .04 <= asyncio.get_running_loop().time() - started < .5
    assert not calls and sent[0]["status"] == 408
    assert (b"cache-control", b"no-store") in sent[0]["headers"]
    assert ((b"connection", b"close") in sent[0]["headers"]) == (version == "1.1")


def _append_sender(sent):
    async def send(message):
        sent.append(message)
    return send


async def test_body_timeout_keeps_cors_and_propagates_external_cancellation():
    events = []
    app = FastAPI()

    @app.post("/command")
    async def command(payload: dict):
        events.append(payload)
        return payload

    app.add_middleware(RequestBodyLimitMiddleware, body_timeout_seconds=.03)
    app.add_middleware(CORSMiddleware, allow_origins=["https://health.example"])

    async def stalled():
        yield b'{"query":"'
        await asyncio.sleep(10)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/command", content=stalled(),
                                     headers={"Origin": "https://health.example"})
    assert response.status_code == 408 and not events
    assert response.headers["access-control-allow-origin"] == "https://health.example"

    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await RequestBodyLimitMiddleware(app)(
            {"type": "http", "headers": []}, cancelled, _append_sender([]))


async def test_final_chunk_returning_after_deadline_is_rejected_before_admission():
    calls, sent = [], []

    async def receive():
        # A delayed event loop can resume receive before the timeout callback runs.
        time.sleep(.03)
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def app(scope, receive, send):
        calls.append("admitted")

    await RequestBodyLimitMiddleware(app, body_timeout_seconds=.01)(
        {"type": "http", "headers": []}, receive, _append_sender(sent))
    assert not calls and sent[0]["status"] == 408
    assert json.loads(sent[1]["body"]) == {"detail": "Request body timed out."}


async def test_slow_oversize_response_does_not_start_a_second_timeout_response():
    sent = []
    first_body = True

    async def receive():
        return {"type": "http.request", "body": b"xx", "more_body": False}

    async def app(scope, receive, send):
        pytest.fail("An oversized body must never reach the application")

    async def send(message):
        nonlocal first_body
        sent.append(message)
        if message["type"] == "http.response.body" and first_body:
            first_body = False
            await asyncio.sleep(.03)

    await RequestBodyLimitMiddleware(app, max_body_bytes=1, body_timeout_seconds=.01)(
        {"type": "http", "headers": []}, receive, send)
    assert [message["status"] for message in sent
            if message["type"] == "http.response.start"] == [413]
    assert json.loads(sent[-1]["body"]) == {"detail": "Request body is too large."}


async def test_real_server_closes_stalled_upload_and_accepts_next_connection():
    import uvicorn

    events = []
    app = FastAPI()

    @app.post("/command")
    async def command(payload: dict):
        events.append(payload)
        return payload

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(RequestBodyLimitMiddleware, body_timeout_seconds=.05)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        task = asyncio.create_task(server.serve(sockets=[listener]))
        writer = None
        try:
            async with asyncio.timeout(3):
                while not server.started:
                    await asyncio.sleep(.01)
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(b"POST /command HTTP/1.1\r\nHost: localhost\r\n"
                             b"Content-Length: 100\r\n\r\nx")
                await writer.drain()
                response = await reader.read()
                assert b"408 Request Timeout" in response and not events
                async with AsyncClient() as client:
                    assert (await client.get(f"http://127.0.0.1:{port}/health")).status_code == 200
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            server.should_exit = True
            await asyncio.wait_for(task, 3)
