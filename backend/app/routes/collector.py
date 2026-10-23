"""Routes required by the independent Python API client."""
from fastapi import APIRouter

from app.routes.catalog import router as catalog_router
from app.routes.diagnostics import router as diagnostics_router
from app.routes.searches import router as searches_router

router = APIRouter(prefix="/collector")
for child_router in (catalog_router, searches_router, diagnostics_router):
    router.include_router(child_router)
