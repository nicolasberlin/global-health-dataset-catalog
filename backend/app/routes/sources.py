from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.database import (
    DATA_SOURCE_KEY_PATTERN_TEXT,
    DuplicateDataSourceKeyError,
    InvalidDataSourceKeyError,
    InvalidDataSourceURLError,
    ReservedDataSourceKeyError,
    create_data_source,
    get_data_source,
    list_data_sources,
    normalize_data_source_key,
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
    source_key: str = Field(min_length=1, pattern=DATA_SOURCE_KEY_PATTERN_TEXT)
    name: str = Field(min_length=1)
    description: str = ""
    theme: str = Field(default="General", min_length=1)
    page_url: HttpUrl

    @field_validator("source_key", mode="before")
    @classmethod
    def normalize_source_key(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_data_source_key(value)
        return value

    @field_validator("name", "description", "theme", mode="before")
    @classmethod
    def strip_text_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class DataSourcesResponse(BaseModel):
    items: list[DataSource]


@router.get("")
async def list_sources() -> DataSourcesResponse:
    return DataSourcesResponse(items=await list_data_sources())


@router.post("", status_code=201)
async def create_source(source: DataSourceCreate) -> DataSource:
    try:
        saved_source = await create_data_source(
            source.source_key,
            source.name,
            source.description,
            source.theme,
            str(source.page_url),
        )
    except ReservedDataSourceKeyError as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception
    except DuplicateDataSourceKeyError as exception:
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    except (InvalidDataSourceKeyError, InvalidDataSourceURLError) as exception:
        raise HTTPException(status_code=400, detail=str(exception)) from exception

    return DataSource(**saved_source)


@router.get("/{source_id}/page")
async def open_source_page(source_id: int) -> RedirectResponse:
    source = await get_data_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    return RedirectResponse(str(source["page_url"]))
