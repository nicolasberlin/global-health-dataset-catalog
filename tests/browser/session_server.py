"""HTTPS harness for browser session tests; never used by the deployed app."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from unittest.mock import AsyncMock, patch

import uvicorn
from app.routes.sessions import router
from app.security import APIPrincipal, require_api_principal, validate_api_security_configuration
from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def page():
    return "<!doctype html><title>Visitor session browser test</title>"


@app.get("/identity")
@app.post("/identity")
async def identity(principal: Annotated[APIPrincipal, Depends(require_api_principal)]):
    return {"owner_id": principal.owner_id}


if __name__ == "__main__":
    os.environ.update(
        API_AUTH_MODE="public",
        API_PUBLIC_ORIGIN="https://localhost:9443",
        API_SESSION_SECRET="browser-test-only-secret-not-for-deployment",
    )
    validate_api_security_configuration()
    with TemporaryDirectory(prefix="visitor-session-tls-") as directory:
        cert = str(Path(directory) / "cert.pem")
        key = str(Path(directory) / "key.pem")
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", key, "-out", cert, "-days", "1", "-subj", "/CN=localhost",
        ], check=True, capture_output=True)
        # Only quota persistence is replaced. PostgreSQL quota tests cover that layer.
        # Cookie issuance, signing, Origin enforcement and authentication are production code.
        with patch("app.security.consume_quota_limits", new=AsyncMock()):
            uvicorn.run(app, host="127.0.0.1", port=9443, ssl_certfile=cert,
                        ssl_keyfile=key, log_level="warning")
