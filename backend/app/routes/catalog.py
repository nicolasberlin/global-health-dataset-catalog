"""Public, bounded catalog reads and dataset lookups."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.database import get_collected_datasets
from app.routes.collector_presenters import _collector_collected_dataset
from app.routes.collector_schemas import CollectorCollectionResponse

router = APIRouter(tags=["collector"])


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
