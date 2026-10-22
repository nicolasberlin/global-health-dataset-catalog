"""Explicit identity injection for route/store tests; real cookies have separate HTTP tests."""

from app.auth.security import APIPrincipal, require_api_principal
from fastapi import HTTPException, Request


def headers(owner="alice"):
    return {"X-Test-Owner": owner}


def inject_owners(application):
    async def owner(request: Request):
        identity = request.headers.get("x-test-owner")
        if identity not in {"alice", "bob", "charlie"}:
            raise HTTPException(401, "A test owner is required.")
        return APIPrincipal(identity)

    application.dependency_overrides[require_api_principal] = owner
    return application
