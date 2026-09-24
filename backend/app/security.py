"""Authentication and per-principal limits for protected API operations."""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Literal, Optional

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from app.db.api_quotas import consume_quota_limits
from app.quota_policy import (
    QuotaExceeded,
    QuotaUnavailable,
    WorkAdmission,
    classification_admission,
    owner_quota,
    public_daily_quota,
    public_ip_quota,
    validate_quota_configuration,
)
from app.visitor_sessions import (
    SESSION_COOKIE_NAME,
    VisitorSessionSettings,
    visitor_owner_id,
    visitor_session_settings,
)

APIQuotaOperation = Literal[
    "repository_search",
    "repository_classification",
]

_bearer_scheme = HTTPBearer(auto_error=False, description="Used when API_AUTH_MODE=token.")
_visitor_scheme = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    auto_error=False,
    description="Used when API_AUTH_MODE=public. Obtain the cookie with POST /session.",
)


@dataclass(frozen=True)
class APIPrincipal:
    """Authenticated API caller used to own searches and consume quotas."""

    owner_id: str
    client_key: str | None = None


def validate_api_security_configuration() -> None:
    """Fail startup when authentication or quota configuration is unsafe."""

    mode = api_auth_mode()
    if mode == "token":
        _configured_access_tokens()
    elif mode == "public":
        visitor_session_settings()
    validate_quota_configuration(public=mode == "public")


async def require_api_principal(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],  # noqa: UP045 - evaluated on Python 3.9.
        Depends(_bearer_scheme),
    ],
    request: Request,
    response: Response,
    visitor_cookie: Annotated[Optional[str], Depends(_visitor_scheme)] = None,  # noqa: UP045
) -> APIPrincipal:
    """Resolve an owner using only the credential accepted by the deployment mode."""

    mode = api_auth_mode()
    if mode == "public":
        settings = visitor_session_settings()
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            _require_session_origin(request, settings)
        if request.headers.get("authorization") is not None:
            raise HTTPException(status_code=401, detail="Public access requires a visitor session.")
        owner_id = visitor_owner_id(visitor_cookie, settings)
        if owner_id is None:
            raise HTTPException(status_code=401, detail="Visitor session is missing or expired.")
        response.headers["Cache-Control"] = "no-store"
        return APIPrincipal(owner_id=owner_id, client_key=public_client_key(request, settings))

    if mode == "local":
        local_hosts = {"127.0.0.1", "::1", "localhost"}
        origin = request.headers.get("origin")
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in local_hosts
            or origin not in {None, "http://127.0.0.1:5173", "http://localhost:5173"}
            or request.headers.get("x-forwarded-for")
            or request.headers.get("forwarded")
        ):
            raise HTTPException(status_code=403, detail="Local access only.")
        return APIPrincipal(owner_id="local-user")

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not 1 <= len(credentials.credentials) <= 512
    ):
        raise _authentication_error()

    try:
        configured_tokens = _configured_access_tokens()
    except RuntimeError as exception:
        raise HTTPException(
            status_code=503,
            detail="API authentication is not configured.",
        ) from exception

    matched_owner = None
    for owner_id, expected_token in configured_tokens.items():
        if hmac.compare_digest(
            credentials.credentials.encode("utf-8"),
            expected_token.encode("utf-8"),
        ):
            matched_owner = owner_id

    if matched_owner is None:
        raise _authentication_error()
    return APIPrincipal(owner_id=matched_owner)


async def enforce_api_quota(
    principal: APIPrincipal,
    operation: APIQuotaOperation,
) -> None:
    """Consume an atomic PostgreSQL quota unit or reject the request."""

    quotas = (owner_quota(principal.owner_id, operation),)
    if principal.client_key is not None:
        quotas += (public_ip_quota(principal.client_key, operation),)
    with quota_http_errors():
        await consume_quota_limits(quotas)


def work_admission(principal: APIPrincipal) -> WorkAdmission:
    return classification_admission(principal.owner_id, principal.client_key)


async def enforce_public_online_quota(principal: APIPrincipal) -> None:
    if principal.client_key is not None:
        with quota_http_errors():
            await consume_quota_limits((public_daily_quota("online_daily"),))


async def enforce_session_creation_quota(
    request: Request, settings: VisitorSessionSettings,
) -> None:
    with quota_http_errors():
        client_key = public_client_key(request, settings)
        await consume_quota_limits((public_ip_quota(client_key, "session"),))


def public_client_key(request: Request, settings: VisitorSessionSettings) -> str:
    # The ASGI server resolves trusted proxies. Never parse client-supplied forwarding headers here.
    try:
        address = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError as exception:
        raise HTTPException(status_code=503, detail="Client address is unavailable.") from exception
    if isinstance(address, ipaddress.IPv6Address):
        address = address.ipv4_mapped or ipaddress.ip_network(f"{address}/64", strict=False)
    digest = hmac.new(
        settings.secret.encode(), f"public-ip:{address}".encode(), "sha256",
    ).hexdigest()
    return f"public:ip:{digest}"


@contextmanager
def quota_http_errors() -> Iterator[None]:
    try:
        yield
    except QuotaExceeded as exception:
        raise HTTPException(status_code=429, detail=str(exception), headers={
            "Retry-After": str(exception.retry_after_seconds),
        }) from exception
    except QuotaUnavailable as exception:
        raise HTTPException(
            status_code=503, detail="API quota service is unavailable.",
        ) from exception


def api_auth_mode() -> str:
    mode = os.environ.get("API_AUTH_MODE", "token")
    if mode not in {"token", "local", "public"}:
        raise RuntimeError("API_AUTH_MODE must be token, local or public.")
    return mode


def require_public_session_bootstrap(request: Request) -> VisitorSessionSettings:
    """Keep cookie issuance and origin checks under the same access policy."""

    if api_auth_mode() != "public":
        raise HTTPException(status_code=404, detail="Not found")
    settings = visitor_session_settings()
    _require_session_origin(request, settings)
    return settings


def _require_session_origin(request: Request, settings: VisitorSessionSettings) -> None:
    # Fail closed for missing/null origins too. CORS alone does not prevent CSRF.
    if request.headers.get("origin") != settings.origin:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def _configured_access_tokens() -> dict[str, str]:
    raw_value = os.environ.get("API_ACCESS_TOKENS", "")
    if not raw_value:
        raise RuntimeError(
            "API_ACCESS_TOKENS must be a JSON object mapping owner IDs to Bearer tokens."
        )

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exception:
        raise RuntimeError("API_ACCESS_TOKENS must contain valid JSON.") from exception

    if not isinstance(parsed, dict) or not parsed:
        raise RuntimeError("API_ACCESS_TOKENS must contain at least one owner and token.")

    configured_tokens: dict[str, str] = {}
    for owner_value, token_value in parsed.items():
        if not isinstance(owner_value, str) or not owner_value.strip():
            raise RuntimeError("API access-token owner IDs must be non-empty strings.")
        if owner_value != owner_value.strip() or len(owner_value) > 200:
            raise RuntimeError(
                "API access-token owner IDs must be trimmed and at most 200 characters."
            )
        if not isinstance(token_value, str) or token_value != token_value.strip():
            raise RuntimeError("API access tokens must be trimmed strings.")
        if not 32 <= len(token_value) <= 512:
            raise RuntimeError("API access tokens must contain between 32 and 512 characters.")
        if token_value in configured_tokens.values():
            raise RuntimeError("Each API access token must identify exactly one owner.")
        configured_tokens[owner_value] = token_value

    return configured_tokens


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Valid Bearer authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
