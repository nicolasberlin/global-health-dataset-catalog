"""Authentication and per-principal limits for protected API operations."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Annotated, Literal, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.api_quotas import consume_api_quota

APIQuotaOperation = Literal[
    "repository_search",
    "repository_classification",
    "collection_start",
    "source_creation",
]

_QUOTA_ENVIRONMENT_VARIABLES: dict[APIQuotaOperation, tuple[str, int]] = {
    "repository_search": ("API_SEARCH_REQUESTS_PER_MINUTE", 10),
    "repository_classification": ("API_CLASSIFICATION_REQUESTS_PER_MINUTE", 20),
    "collection_start": ("API_COLLECTION_REQUESTS_PER_MINUTE", 5),
    "source_creation": ("API_SOURCE_CREATION_REQUESTS_PER_MINUTE", 10),
}
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class APIPrincipal:
    """Authenticated API caller used to own searches and consume quotas."""

    owner_id: str


def validate_api_security_configuration() -> None:
    """Fail startup when authentication or quota configuration is unsafe."""

    _configured_access_tokens()
    for operation in _QUOTA_ENVIRONMENT_VARIABLES:
        _quota_limit(operation)


async def require_api_principal(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],  # noqa: UP045 - evaluated on Python 3.9.
        Depends(_bearer_scheme),
    ],
) -> APIPrincipal:
    """Authenticate one configured Bearer token without exposing token values."""

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

    try:
        decision = await consume_api_quota(
            principal.owner_id,
            operation,
            limit=_quota_limit(operation),
        )
    except Exception as exception:  # noqa: BLE001 - quotas fail closed.
        raise HTTPException(
            status_code=503,
            detail="API quota service is unavailable.",
        ) from exception

    if decision.allowed:
        return

    raise HTTPException(
        status_code=429,
        detail="API request quota exceeded.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


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


def _quota_limit(operation: APIQuotaOperation) -> int:
    environment_name, default_limit = _QUOTA_ENVIRONMENT_VARIABLES[operation]
    raw_value = os.environ.get(environment_name, str(default_limit))
    try:
        limit = int(raw_value)
    except ValueError as exception:
        raise RuntimeError(f"{environment_name} must be an integer.") from exception
    if not 1 <= limit <= 10_000:
        raise RuntimeError(f"{environment_name} must be between 1 and 10000.")
    return limit


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Valid Bearer authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
