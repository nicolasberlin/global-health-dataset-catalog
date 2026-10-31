"""Reserve and associate collection follow-up for accepted repository candidates.

Classification completion calls the private reservation helper on its existing
connection and transaction so the decision and its follow-up commit together.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from app.db.collection.job_reads import _collection_job_to_dict
from app.db.collection.jobs import _insert_collection_job
from app.db.connection import _fetchall, _fetchone, _require_database_pool
from app.db.owner_ids import validate_owner_id
from app.db.schema import _require_current_schema
from collector.url_utils import require_http_url


@dataclass(frozen=True)
class CollectionJobReservation:
    """Result of atomically reserving collection for one repository candidate."""

    job: dict[str, object] | None
    created: bool
    already_collected: bool
    dataset_ids: tuple[int, ...] = ()


async def reserve_repository_candidate_collection_job(
    candidate_id: UUID,
    owner_id: str,
) -> CollectionJobReservation:
    """Reserve follow-up explicitly; progress reads must never create work."""

    async with _require_database_pool().connection() as connection:
        await _require_current_schema(connection)
        async with connection.transaction():
            return await _reserve_repository_candidate_collection_job(
                connection,
                candidate_id,
                owner_id,
            )


async def _reserve_repository_candidate_collection_job(
    connection: AsyncConnection[DictRow],
    candidate_id: UUID,
    owner_id: str,
) -> CollectionJobReservation:
    """Reserve on the caller's transaction, including candidate associations.

    Lock the owned candidate before serializing by URL so distinct searches
    reuse the same active job. Any failure must roll back the caller's decision
    and reservation together; this helper never opens another transaction.
    """

    candidate = await _fetchone(
        connection,
        """
        SELECT candidate.id, candidate.url, candidate.classification_status
        FROM repository_candidates AS candidate
        JOIN search_sessions AS session
          ON session.id = candidate.search_session_id
        WHERE candidate.id = %s AND session.owner_id = %s
        FOR UPDATE OF candidate
        """,
        (candidate_id, validate_owner_id(owner_id)),
    )
    if candidate is None:
        raise ValueError("Repository candidate not found.")
    if str(candidate["classification_status"]) != "accepted":
        raise ValueError("Only an accepted candidate can be collected.")

    source_url = require_http_url(str(candidate["url"]))
    # Different searches can persist different candidate IDs for the
    # same URL, so URL-level serialization is also required.
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (source_url,),
    )
    reservation_state = await _fetchone(
        connection,
        """
        SELECT
            EXISTS (
                SELECT 1
                FROM collected_datasets AS dataset
                WHERE dataset.dataset_url = %s
            ) OR EXISTS (
                SELECT 1 FROM dataset_discovery_observations AS observation
                WHERE observation.source_url = %s
            ) AS already_collected,
            active_job.id,
            active_job.source_url,
            active_job.kind,
            active_job.repository_candidate_id,
            active_job.status,
            active_job.saved_count,
            active_job.discovered_count,
            active_job.analyzed_count,
            active_job.accepted_count,
            active_job.rejected_count,
            active_job.invalid_distribution_count,
            active_job.discovery_methods,
            active_job.classification_progress,
            active_job.message,
            active_job.error, active_job.errors, active_job.outcome,
            active_job.created_at,
            active_job.updated_at,
            active_job.finished_at, active_job.collection_deadline_at,
            active_job.collection_coverage, active_job.collection_method_summary
        FROM (VALUES (1)) AS singleton(value)
        LEFT JOIN LATERAL (
            SELECT id, source_url, kind, repository_candidate_id,
                   status, saved_count, discovered_count,
                   analyzed_count, accepted_count, rejected_count,
                   invalid_distribution_count, discovery_methods, classification_progress,
                   message,
                   error, errors, outcome, created_at, updated_at, finished_at,
                   collection_deadline_at, collection_coverage, collection_method_summary
            FROM collection_jobs
            WHERE (
                repository_candidate_id = %s
                OR (kind = 'repository_candidate' AND source_url = %s)
            )
              AND status IN ('pending', 'running')
            ORDER BY id DESC
            LIMIT 1
        ) AS active_job ON TRUE
        """,
        (source_url, source_url, candidate_id, source_url),
    )
    if reservation_state is None:
        raise RuntimeError("Automatic collection lookup returned no row.")
    if bool(reservation_state["already_collected"]):
        return CollectionJobReservation(
            job=None,
            created=False,
            already_collected=True,
            dataset_ids=tuple(await _existing_dataset_ids(connection, source_url)),
        )

    if reservation_state["id"] is not None:
        await _associate_job_candidate(connection, reservation_state["id"], candidate_id)
        return CollectionJobReservation(
            job=_collection_job_to_dict(reservation_state),
            created=False,
            already_collected=False,
        )

    new_job = await _insert_collection_job(
        connection,
        source_url,
        kind="repository_candidate",
        repository_candidate_id=candidate_id,
    )
    if new_job is None:
        raise RuntimeError("Collection job insert did not return a row.")
    await _associate_job_candidate(connection, new_job["id"], candidate_id)
    return CollectionJobReservation(
        job=_collection_job_to_dict(new_job),
        created=True,
        already_collected=False,
    )


async def _associate_job_candidate(
    connection: AsyncConnection[DictRow], job_id: int, candidate_id: UUID,
) -> None:
    """Attach the candidate once using the caller's current transaction."""
    await connection.execute(
        """
        INSERT INTO collection_job_candidates (job_id, candidate_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
        """,
        (job_id, candidate_id),
    )


async def _existing_dataset_ids(
    connection: AsyncConnection[DictRow], source_url: str,
) -> list[int]:
    """Resolve saved results by record URL or by its discovery observations."""
    rows = await _fetchall(
        connection,
        """SELECT id FROM collected_datasets WHERE dataset_url = %s
           UNION
           SELECT dataset_id AS id FROM dataset_discovery_observations
           WHERE source_url = %s
           ORDER BY id""",
        (source_url, source_url),
    )
    return [int(row["id"]) for row in rows]
