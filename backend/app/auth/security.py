"""Authentication and per-principal limits for protected API operations."""

from __future__ import annotations

import hmac
import ipaddress
import os
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import APIKeyCookie

from app.auth.sessions import (
    HTTP_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    VisitorSessionSettings,
    visitor_owner_id,
    visitor_session_settings,
)
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

APIQuotaOperation = Literal[
    "repository_search",
    "repository_classification",
]

_visitor_scheme = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    auto_error=False,
    description="Used when API_AUTH_MODE=public. Obtain the cookie with POST /session.",
)
_http_visitor_scheme = APIKeyCookie(
    name=HTTP_SESSION_COOKIE_NAME,
    scheme_name="InternalHTTPSession",
    auto_error=False,
    description="Only for explicitly enabled internal HTTP visitor sessions.",
)


@dataclass(frozen=True)
class APIPrincipal:
    """Server-derived caller identity used to own searches and consume quotas."""

    owner_id: str
    client_key: str | None = None


def validate_api_security_configuration() -> None:
    """Fail startup when authentication or quota configuration is unsafe."""

    mode = api_auth_mode()
    if mode == "public":
        visitor_session_settings()
    validate_quota_configuration(public=mode == "public")


async def require_api_principal(
    request: Request,
    response: Response,
    visitor_cookie: Annotated[str | None, Depends(_visitor_scheme)] = None,
    http_cookie: Annotated[str | None, Depends(_http_visitor_scheme)] = None,
) -> APIPrincipal:
    """Resolve an owner using only the credential accepted by the deployment mode."""

    mode = api_auth_mode()
    if mode == "public":
        settings = visitor_session_settings()
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            _require_session_origin(request, settings)
        owner_id = visitor_owner_id(visitor_cookie if settings.secure else http_cookie, settings)
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

    raise RuntimeError("Unsupported access mode.")


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
    mode = os.environ.get("API_AUTH_MODE", "local")
    if mode not in {"local", "public"}:
        raise RuntimeError("API_AUTH_MODE must be local or public.")
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


def api_cors_origins() -> list[str]:
    """Validate the explicit browser origins allowed to call this API."""
    value = os.getenv("API_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError as exception:
            raise RuntimeError(
                "API_CORS_ORIGINS must contain valid HTTP(S) origins."
            ) from exception
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path
                or parsed.query or parsed.fragment or parsed.username or parsed.password
                or any(character.isspace() for character in origin) or "\\" in origin):
            raise RuntimeError(
                "API_CORS_ORIGINS must contain explicit HTTP(S) origins without paths."
            )
    return origins


def configure_access_openapi(application) -> None:
    """Describe the credential actually accepted by this deployment."""
    original_openapi = application.openapi

    def openapi():
        schema = deepcopy(original_openapi())
        scheme = None
        if api_auth_mode() == "public":
            scheme = "APIKeyCookie" if visitor_session_settings().secure else "InternalHTTPSession"
        for path in schema["paths"].values():
            for operation in path.values():
                if not isinstance(operation, dict) or "security" not in operation:
                    continue
                if scheme is None:
                    operation.pop("security")
                else:
                    operation["security"] = [{scheme: []}]
        schemes = schema.get("components", {}).get("securitySchemes", {})
        for name in list(schemes):
            if name != scheme:
                del schemes[name]
        return schema

    application.openapi = openapi
