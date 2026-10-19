"""Signed, expiring visitor identities; no accounts or database session records."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import uuid4

from itsdangerous import BadData, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "__Host-global-health-session"
HTTP_SESSION_COOKIE_NAME = "global-health-session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_SIGNING_SALT = "global-health-visitor-session-v1"


@dataclass(frozen=True)
class VisitorSessionSettings:
    secret: str = field(repr=False)
    origin: str

    @property
    def secure(self) -> bool:
        return self.origin.startswith("https://")

    @property
    def cookie_name(self) -> str:
        return SESSION_COOKIE_NAME if self.secure else HTTP_SESSION_COOKIE_NAME


def visitor_session_settings() -> VisitorSessionSettings:
    """Require HTTPS unless HTTP is explicitly enabled for an internal deployment."""

    allow_http = os.environ.get("API_ALLOW_INSECURE_HTTP_SESSIONS", "false").lower()
    if allow_http not in {"true", "false"}:
        raise RuntimeError("API_ALLOW_INSECURE_HTTP_SESSIONS must be true or false.")

    secret = os.environ.get("API_SESSION_SECRET", "")
    if secret != secret.strip() or not 32 <= len(secret) <= 512:
        raise RuntimeError("API_SESSION_SECRET must contain 32 to 512 characters without padding.")

    origin = os.environ.get("API_PUBLIC_ORIGIN", "")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
        valid = (
            (parsed.scheme == "https" or (parsed.scheme == "http" and allow_http == "true"))
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and not re.search(r"[\s\\]", origin)
        )
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError(
            "API_PUBLIC_ORIGIN must be an HTTPS origin without a path. "
            "Internal HTTP requires API_ALLOW_INSECURE_HTTP_SESSIONS=true."
        )

    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    normalized_origin = f"{parsed.scheme}://{host}" + (
        f":{port}" if port not in {None, default_port} else ""
    )
    return VisitorSessionSettings(secret=secret, origin=normalized_origin)


def new_visitor_cookie(settings: VisitorSessionSettings) -> str:
    return _serializer(settings).dumps(uuid4().hex)


def visitor_owner_id(cookie: str | None, settings: VisitorSessionSettings) -> str | None:
    """Accept only a signed, unexpired server-issued identity, never client owner IDs."""

    if not cookie or len(cookie) > 512:
        return None
    try:
        identity = _serializer(settings).loads(cookie, max_age=SESSION_MAX_AGE_SECONDS)
    except BadData:
        return None
    if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{32}", identity) is None:
        return None
    return f"visitor:{identity}"


def _serializer(settings: VisitorSessionSettings) -> URLSafeTimedSerializer:
    # An exposed internal HTTP credential must not become a valid HTTPS session.
    salt = _SIGNING_SALT if settings.secure else f"{_SIGNING_SALT}-insecure-http"
    return URLSafeTimedSerializer(settings.secret, salt=salt)
