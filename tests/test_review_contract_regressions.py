"""Browser integrations can read the API's retry and resource-location headers."""

import pytest
from app.main import app
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def cors_configuration():
    # Exercise the production middleware configuration without starting workers,
    # touching PostgreSQL, or installing test-only routes on the shared app.
    return next(item for item in app.user_middleware if item.cls is CORSMiddleware)


@pytest.mark.parametrize(
    ("status_code", "header", "value"),
    [(429, "Retry-After", "73"), (202, "Location", "/collector/searches/search-id/progress")],
)
async def test_cross_origin_responses_expose_control_headers(
    cors_configuration,
    status_code,
    header,
    value,
):
    origin = cors_configuration.kwargs["allow_origins"][0]
    response = JSONResponse({}, status_code=status_code, headers={header: value})
    middleware = cors_configuration.cls(response, **cors_configuration.kwargs)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://api"
    ) as client:
        received = await client.get("/", headers={"Origin": origin})

    assert received.status_code == status_code
    assert received.headers[header] == value
    assert received.headers["access-control-allow-origin"] == origin
    assert received.headers["access-control-allow-credentials"] == "true"
    exposed = {
        name.strip().lower()
        for name in received.headers["access-control-expose-headers"].split(",")
    }
    assert header.lower() in exposed


async def test_exposed_headers_do_not_allow_an_unconfigured_origin(cors_configuration):
    response = JSONResponse({}, status_code=429, headers={"Retry-After": "73"})
    middleware = cors_configuration.cls(response, **cors_configuration.kwargs)
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://api"
    ) as client:
        received = await client.get("/", headers={"Origin": "https://untrusted.example"})

    assert received.status_code == 429
    assert "access-control-allow-origin" not in received.headers
