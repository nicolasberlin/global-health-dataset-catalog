"""Assemble the core search, diagnostic and dataset routes under /collector.

main.create_app() registers this router. For example, /searches in searches.py
becomes /collector/searches here. This module only registers routes; their
handlers and the background workers perform the actual work.
"""
from fastapi import APIRouter

from app.api.catalog import router as catalog_router
from app.api.diagnostics import router as diagnostics_router
from app.api.searches import router as searches_router

router = APIRouter(prefix="/collector")
for child_router in (catalog_router, searches_router, diagnostics_router):
    router.include_router(child_router)
