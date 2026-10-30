"""Append and read discovery observations linking collected datasets to source jobs."""

from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.connection import Row, _fetchall, _require_database_pool
from app.db.schema import _require_current_schema
from app.db.serialization import _format_timestamp


async def list_dataset_discovery_observations(
    dataset_id: int | None = None,
) -> list[dict[str, int | str | None]]:
    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        rows = await _select_dataset_discovery_observations(connection, dataset_id)

    return [_dataset_discovery_observation_to_dict(row) for row in rows]


async def _insert_dataset_discovery_observation(
    connection: AsyncConnection[DictRow],
    dataset_id: int,
    source_url: str,
    discovery_method: str,
    collection_job_id: int | None,
) -> None:
    """Append one observation even when the dataset URL already existed."""

    await connection.execute(
        """
        INSERT INTO dataset_discovery_observations (
            collection_job_id, dataset_id, source_url, discovery_method, observed_at
        )
        VALUES (%s, %s, %s, %s, NOW())
        """,
        (collection_job_id, dataset_id, source_url, discovery_method),
    )


async def _select_dataset_discovery_observations(
    connection: AsyncConnection[DictRow],
    dataset_id: int | None,
) -> list[Row]:
    sql = """
        SELECT observation.id, observation.dataset_id, dataset.dataset_url,
               observation.collection_job_id,
               observation.source_url, observation.discovery_method,
               observation.observed_at
        FROM dataset_discovery_observations AS observation
        JOIN collected_datasets AS dataset ON dataset.id = observation.dataset_id
    """
    parameters: tuple[int, ...] = ()
    if dataset_id is not None:
        sql += " WHERE observation.dataset_id = %s"
        parameters = (dataset_id,)
    sql += " ORDER BY observation.observed_at DESC, observation.id DESC"

    return await _fetchall(connection, sql, parameters)


def _dataset_discovery_observation_to_dict(
    row: Row,
) -> dict[str, int | str | None]:
    return {
        "id": int(row["id"]),
        "dataset_id": int(row["dataset_id"]),
        "dataset_url": str(row["dataset_url"]),
        "collection_job_id": (
            int(row["collection_job_id"])
            if row["collection_job_id"] is not None
            else None
        ),
        "source_url": str(row["source_url"]),
        "discovery_method": str(row["discovery_method"]),
        "observed_at": _format_timestamp(row["observed_at"]),
    }
