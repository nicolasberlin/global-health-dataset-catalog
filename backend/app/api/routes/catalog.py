"""Return saved catalogue datasets by ID, independently of search ownership.

The catalogue is public in both access modes. The Python client calls this route
with IDs from search progress to retrieve the full dataset records.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.presenters.catalog import build_catalog_dataset_view
from app.api.schemas.catalog import CatalogDatasetsResponse
from app.db.catalog.datasets import get_collected_datasets

router = APIRouter(tags=["collector"])


@router.get("/collected-datasets/by-id")
async def get_catalog_datasets_by_id(
    ids: Annotated[
        list[Annotated[int, Query(ge=1, le=2147483647)]],
        Query(
            min_length=1,
            max_length=100,
        ),
    ],
) -> CatalogDatasetsResponse:
    """Read up to 100 saved dataset IDs and prepare their API response.

    FastAPI validates the IDs before this handler runs. Missing IDs are omitted;
    this read does not discover, collect or validate any new dataset.
    """
    return CatalogDatasetsResponse(
        items=[
            build_catalog_dataset_view(dataset) for dataset in await get_collected_datasets(ids)
        ],
    )
