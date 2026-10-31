"""Loopback-only sidecar; no application workers, migrations or collection writes."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

import httpx
from app.auth.security import APIPrincipal, api_auth_mode
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .attempts import group_attempts
from .comparison import compare
from .history import History
from .settings import Settings
from .snapshots import Snapshots

ORIGINS = {"http://127.0.0.1:5174", "http://localhost:5174"}


async def principal(
    request: Request,
    response: Response,
):
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or request.headers.get("origin") not in ORIGINS | {None}
        or request.headers.get("forwarded")
        or request.headers.get("x-forwarded-for")
    ):
        raise HTTPException(403, "Local laboratory access only.")
    if api_auth_mode() != "local":
        raise HTTPException(503, "The laboratory requires local access.")
    return APIPrincipal("local-user")


Owner = Annotated[APIPrincipal, Depends(principal)]


class SnapshotCaptureRequest(BaseModel):
    candidate_id: UUID
    label: str = Field(default="", max_length=150)
    expected_result: str = Field(default="", max_length=2000)
    suspected_cause: str = Field(default="", max_length=2000)
    change_tested: str = Field(default="", max_length=2000)
    learned: str = Field(default="", max_length=2000)


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(application):
        if api_auth_mode() != "local":
            raise RuntimeError("Run the laboratory with API_AUTH_MODE=local.")
        config = settings or Settings.configured()
        history = History(config.database_url)
        await history.open()
        try:
            application.state.history = history
            application.state.snapshots = Snapshots(config.evidence_dir)
            async with httpx.AsyncClient(
                base_url=config.api_base, timeout=20, trust_env=False, follow_redirects=False
            ) as client:
                application.state.client = client
                yield
        finally:
            await history.close()

    application = FastAPI(title="Local search laboratory", lifespan=lifespan)

    @application.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/lab/config")
    async def config():
        return {
            "auth_mode": api_auth_mode(),
            "mode": "observation",
            "evidence_scope": "Current state and recorded method history",
        }

    @application.get("/lab/searches")
    async def searches(
        request: Request,
        owner: Owner,
        q: str = Query(default="", max_length=200),
        origin: Literal["database", "online"] = None,
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str = Query(default=None, max_length=500),
    ):
        try:
            return await request.app.state.history.list_searches(
                owner.owner_id,
                query=q,
                origin=origin,
                limit=limit,
                cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(400, "Invalid history cursor.") from exc

    async def observation(search_id, request, owner):
        history = request.app.state.history
        if not await history.owns_search(owner.owner_id, search_id):
            raise HTTPException(404, "Search not found.")
        try:
            async with request.app.state.client.stream(
                "GET",
                f"/collector/searches/{search_id}/diagnostics",
            ) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        response.status_code if response.status_code in {401, 403, 404} else 502,
                        "Unable to read application diagnostics.",
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 8_000_000:
                        raise HTTPException(502, "Diagnostic export exceeds the laboratory limit.")
                    body.extend(chunk)
                trace = json.loads(body)
                if (
                    not isinstance(trace, dict)
                    or not isinstance(trace.get("context"), dict)
                    or trace["context"].get("search_id") != str(search_id)
                ):
                    raise HTTPException(
                        502, "Application and laboratory search evidence do not match."
                    )
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, "Application diagnostics are unavailable.") from exc
        job_ids = [item["job_id"] for item in trace.get("collections", []) if item]
        claims = await history.method_claims(job_ids)
        return {
            "trace": trace,
            "attempts": group_attempts(trace, claims),
            "warning": "Job results are current. Earlier method traces are dated observations, "
            "not complete historical snapshots. Collector versions are unknown.",
        }

    @application.get("/lab/searches/{search_id}")
    async def detail(search_id: UUID, request: Request, owner: Owner):
        return await observation(search_id, request, owner)

    @application.post("/lab/searches/{search_id}/snapshots", status_code=201)
    async def capture(
        search_id: UUID, notes: SnapshotCaptureRequest, request: Request, owner: Owner
    ):
        data = await observation(search_id, request, owner)
        try:
            return request.app.state.snapshots.create(
                owner.owner_id, data, notes.model_dump(exclude={"candidate_id"}), notes.candidate_id
            )
        except ValueError as exc:
            raise HTTPException(404, "Candidate not found in this search.") from exc

    @application.get("/lab/snapshots")
    async def snapshots(request: Request, owner: Owner):
        return {"items": request.app.state.snapshots.list(owner.owner_id)}

    def read_snapshot(request, owner, identifier):
        try:
            return request.app.state.snapshots.read(owner.owner_id, identifier)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Snapshot not found.") from exc
        except ValueError as exc:
            raise HTTPException(409, "Snapshot integrity check failed.") from exc

    @application.get("/lab/snapshots/{identifier}")
    async def snapshot(identifier: UUID, request: Request, owner: Owner):
        return read_snapshot(request, owner, identifier)

    @application.get("/lab/compare/{before}/{after}")
    async def comparison(before: UUID, after: UUID, request: Request, owner: Owner):
        try:
            return compare(
                read_snapshot(request, owner, before), read_snapshot(request, owner, after)
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return application


app = create_app()
