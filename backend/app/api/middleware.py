"""Bound HTTP requests and reject commands when processing is unavailable."""

from __future__ import annotations

import asyncio
import math
import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_REQUEST_BODY_BYTES = 65_536
DEFAULT_REQUEST_BODY_TIMEOUT_SECONDS = 30.0


def configured_max_request_body_bytes() -> int:
    """Reject unsafe configuration instead of silently disabling the limit."""

    try:
        value = int(os.getenv("API_MAX_REQUEST_BODY_BYTES", str(DEFAULT_MAX_REQUEST_BODY_BYTES)))
    except ValueError as exception:
        raise RuntimeError("API_MAX_REQUEST_BODY_BYTES must be an integer.") from exception
    if not 1_024 <= value <= 1_048_576:
        raise RuntimeError("API_MAX_REQUEST_BODY_BYTES must be between 1024 and 1048576.")
    return value


def configured_request_body_timeout_seconds() -> float:
    try:
        value = float(os.getenv("API_REQUEST_BODY_TIMEOUT_SECONDS",
                                str(DEFAULT_REQUEST_BODY_TIMEOUT_SECONDS)))
    except ValueError as exception:
        raise RuntimeError("API_REQUEST_BODY_TIMEOUT_SECONDS must be a number.") from exception
    if not math.isfinite(value) or not 1 <= value <= 120:
        raise RuntimeError("API_REQUEST_BODY_TIMEOUT_SECONDS must be between 1 and 120.")
    return value


class RequestBodyLimitMiddleware:
    """Read at most the configured bytes and replay only complete, accepted bodies.

    Content-Length is an early rejection hint, never the source of truth. Count
    every received chunk so absent or understated headers cannot bypass the cap.
    Place CORS outside this middleware so browsers can read its 413 responses.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int | None = None,
                 body_timeout_seconds: float | None = None) -> None:
        self.app = app
        self.max_body_bytes = (
            configured_max_request_body_bytes() if max_body_bytes is None else max_body_bytes
        )
        if type(self.max_body_bytes) is not int or self.max_body_bytes < 1:
            raise ValueError("max_body_bytes must be a positive integer.")
        self.body_timeout_seconds = (configured_request_body_timeout_seconds()
                                     if body_timeout_seconds is None else body_timeout_seconds)
        if not math.isfinite(self.body_timeout_seconds) or self.body_timeout_seconds <= 0:
            raise ValueError("body_timeout_seconds must be positive and finite.")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                # Malformed lengths still go through the actual-byte check below.
                if value.isdigit():
                    declared = value.lstrip(b"0") or b"0"
                    if len(declared) > 20 or int(declared) > self.max_body_bytes:
                        await self._reject(scope, receive, send)
                        return

        body = bytearray()
        received = 0
        deadline = asyncio.get_running_loop().time() + self.body_timeout_seconds
        while True:
            try:
                async with asyncio.timeout_at(deadline):
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
                    message = await receive()
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
            except TimeoutError:
                headers = {"Cache-Control": "no-store"}
                if scope.get("http_version", "1.1").startswith("1."):
                    headers["Connection"] = "close"
                await JSONResponse({"detail": "Request body timed out."}, status_code=408,
                                   headers=headers)(scope, receive, send)
                return
            if message["type"] == "http.disconnect":
                return  # Never execute a command from an incomplete body.
            received += len(message.get("body", b""))
            if received > self.max_body_bytes:
                await self._reject(scope, receive, send)
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": "Request body is too large."},
            status_code=413,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)


class ApplicationAvailabilityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            from app.workers.state import workers_ready

            state = scope["app"].state
            if getattr(state, "runtime_enforced", False):
                ownership = getattr(state, "ownership", None)
                if (
                    not getattr(state, "ready", False)
                    or ownership is None
                    or not ownership.healthy
                    or not workers_ready()
                ):
                    await JSONResponse(
                        {"detail": "Processing is temporarily unavailable."},
                        status_code=503,
                        headers={"Retry-After": "5", "Cache-Control": "no-store"},
                    )(scope, receive, send)
                    return
        await self.app(scope, receive, send)
