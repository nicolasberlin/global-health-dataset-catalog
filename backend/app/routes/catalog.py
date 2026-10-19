"""Public, bounded catalog reads and dataset lookups."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.database import get_collected_datasets, list_collected_datasets
from app.routes.collector_presenters import _collector_collected_dataset
from app.routes.collector_schemas import CollectorCollectionResponse

router = APIRouter(tags=["collector"])


@router.get("/collected-datasets")
async def list_collected(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[int | None, Query(ge=1, le=2147483647)] = None,
    query: Annotated[str, Query(max_length=300)] = "",
    country: Annotated[str, Query(max_length=200)] = "",
    format: Annotated[str, Query(max_length=100)] = "",
) -> CollectorCollectionResponse:
    datasets = await list_collected_datasets(
        limit=limit + 1,
        before_id=cursor,
        query=query,
        country=country,
        format=format,
    )
    items = datasets[:limit]
    return CollectorCollectionResponse(
        items=[_collector_collected_dataset(dataset) for dataset in items],
        next_cursor=items[-1].database_id if len(datasets) > limit else None,
    )


@router.get("/collected-datasets/by-id")
async def read_collected_by_id(
    ids: Annotated[
        list[Annotated[int, Query(ge=1, le=2147483647)]],
        Query(
            min_length=1,
            max_length=100,
        ),
    ],
) -> CollectorCollectionResponse:
    return CollectorCollectionResponse(
        items=[
            _collector_collected_dataset(dataset) for dataset in await get_collected_datasets(ids)
        ],
    )
