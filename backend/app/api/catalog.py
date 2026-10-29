"""Return saved catalogue datasets by ID, independently of search ownership.

The catalogue is public in both access modes. The Python client calls this route
with IDs from search progress to retrieve the full dataset records.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.presenters import public_collected_dataset
from app.api.schemas import CollectorCollectionResponse
from app.db.catalog import get_collected_datasets

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
    """Read up to 100 saved dataset IDs and prepare their API response.

    FastAPI validates the IDs before this handler runs. Missing IDs are omitted;
    this read does not discover, collect or validate any new dataset.
    """
    return CollectorCollectionResponse(
        items=[
            public_collected_dataset(dataset) for dataset in await get_collected_datasets(ids)
        ],
    )
