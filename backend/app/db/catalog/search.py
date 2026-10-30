"""Normalize catalogue queries and rank persisted datasets with PostgreSQL full-text search."""

from __future__ import annotations

import string

from app.db.catalog.datasets import _collected_dataset_from_rows
from app.db.connection import Row, _fetchall, _require_database_pool
from app.db.schema import DATASET_SEARCH_TEXT_CONFIGURATION, _require_current_schema
from collector.storage.models import CollectedDataset

# Keep this catalog-specific list small; PostgreSQL's language dictionary owns
# grammatical stop words and stemming.
CATALOG_GENERIC_SEARCH_TERMS = {
    "data",
    "dataset",
    "database",
}


def normalize_dataset_search_query(query: str) -> str:
    """Remove catalog-generic terms before PostgreSQL full-text search."""

    meaningful_terms = []
    for term in query.strip().split():
        normalized_term = term.strip(string.punctuation).casefold()
        singular_term = (
            normalized_term[:-1]
            if normalized_term.endswith("s")
            else normalized_term
        )
        if (
            normalized_term in CATALOG_GENERIC_SEARCH_TERMS
            or singular_term in CATALOG_GENERIC_SEARCH_TERMS
        ):
            continue
        meaningful_terms.append(term)

    return " ".join(meaningful_terms)


async def search_collected_datasets(
    query: str,
    limit: int = 10,
) -> list[CollectedDataset]:
    """Search persisted metadata with weighted PostgreSQL full-text ranking.

    An empty query returns no rows, while a non-positive limit raises
    ``ValueError``. Database and deserialization errors propagate. Matching
    distributions are loaded only for the bounded result set.
    """

    normalized_query = query.strip()
    if not normalized_query:
        return []
    if limit < 1:
        raise ValueError("limit must be greater than zero.")

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        dataset_rows = await _fetchall(
            connection,
            f"""
            WITH search_query AS (
                SELECT websearch_to_tsquery(
                    '{DATASET_SEARCH_TEXT_CONFIGURATION}',
                    %s
                ) AS value
            )
            SELECT dataset.id, dataset.source_url, dataset.dataset_url,
                   dataset.title, dataset.description, dataset.publisher,
                   dataset.date_of_publication, dataset.sharing_license, dataset.doi,
                   dataset.metadata_provenance, dataset.record_identity,
                   dataset.hosting_platform, dataset.uploader, dataset.geography,
                   dataset.discovery_method, dataset.dataset_signals,
                   dataset.first_seen_at, dataset.last_seen_at, dataset.updated_at,
                   ts_rank_cd(dataset.search_vector, search_query.value) AS relevance
            FROM collected_datasets AS dataset
            CROSS JOIN search_query
            WHERE dataset.search_vector @@ search_query.value
            ORDER BY relevance DESC, dataset.updated_at DESC
            LIMIT %s
            """,
            (normalized_query, limit),
        )
        dataset_ids = [int(row["id"]) for row in dataset_rows]
        distribution_rows = (
            await _fetchall(
                connection,
                """
                SELECT *
                FROM collected_distributions
                WHERE dataset_id = ANY(%s)
                ORDER BY probability DESC, url
                """,
                (dataset_ids,),
            )
            if dataset_ids
            else []
        )

    distributions_by_dataset_id: dict[int, list[Row]] = {}
    for row in distribution_rows:
        distributions_by_dataset_id.setdefault(int(row["dataset_id"]), []).append(row)

    return [
        _collected_dataset_from_rows(
            dataset_row,
            distributions_by_dataset_id.get(int(dataset_row["id"]), []),
        )
        for dataset_row in dataset_rows
    ]
