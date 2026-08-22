from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, HttpUrl

from app.database import (
    ReservedDataSourceKeyError,
    get_data_source,
    list_data_sources,
    upsert_data_source,
)

router = APIRouter(prefix="/sources", tags=["sources"])


class DataSource(BaseModel):
    id: int
    source_key: str
    name: str
    description: str
    theme: str
    page_url: HttpUrl


class DataSourceCreate(BaseModel):
    source_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    theme: str = Field(default="General", min_length=1)
    page_url: HttpUrl


class DataSourcesResponse(BaseModel):
    items: list[DataSource]


@router.get("")
def list_sources() -> DataSourcesResponse:
    return DataSourcesResponse(items=list_data_sources())


@router.post("", status_code=201)
def create_source(source: DataSourceCreate) -> DataSource:
    try:
        saved_source = upsert_data_source(
            source.source_key,
            source.name,
            source.description,
            source.theme,
            str(source.page_url),
        )
    except ReservedDataSourceKeyError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return DataSource(**saved_source)


@router.get("/{source_id}/page")
def open_source_page(source_id: int) -> RedirectResponse:
    source = get_data_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    return RedirectResponse(str(source["page_url"]))
