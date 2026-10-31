"""Owner-scoped, consistent snapshots of a search and its existing follow-up."""

from __future__ import annotations

from uuid import UUID

from app.db.classification.candidates import _CANDIDATE_COLUMNS, _repository_candidate_to_dict
from app.db.collection.job_reads import _collection_job_to_dict
from app.db.collection.reservations import CollectionJobReservation
from app.db.connection import Row, _fetchall, _fetchone, _require_database_pool
from app.db.owner_ids import validate_owner_id


async def read_search_progress(
    search_id: UUID,
    owner_id: str,
) -> tuple[Row, list[Row], dict[UUID, CollectionJobReservation]] | None:
    """Read one owner's search and follow-up from a single consistent snapshot."""
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            search = await _fetchone(
                connection,
                "SELECT id, query, status, origin, errors, warnings, local_result_count, "
                "discovery_complete, created_at, updated_at, attempt_number "
                "FROM search_sessions WHERE id = %s AND owner_id = %s",
                (search_id, validate_owner_id(owner_id)),
            )
            if search is None:
                return None
            local_result_rows = await _fetchall(
                connection,
                "SELECT dataset_id FROM search_local_results "
                "WHERE search_id = %s ORDER BY position",
                (search_id,),
            )
            search["local_dataset_ids"] = [int(row["dataset_id"]) for row in local_result_rows]
            candidate_rows = await _fetchall(
                connection,
                f"""
                SELECT {_CANDIDATE_COLUMNS} FROM repository_candidates AS candidate
                JOIN search_sessions AS session ON session.id = candidate.search_session_id
                WHERE session.id = %s AND session.owner_id = %s
                ORDER BY candidate.created_at, candidate.id
                """,
                (search_id, owner_id),
            )
            candidates = [_repository_candidate_to_dict(row) for row in candidate_rows]
            accepted_candidate_ids = [
                candidate["id"]
                for candidate in candidates
                if candidate["classification_status"] == "accepted"
            ]
            # Preserve the individual read's rule: the latest explicitly associated
            # job wins, even when another job at the same URL has saved data.
            job_rows = await _fetchall(
                connection,
                """
                SELECT DISTINCT ON (association.candidate_id)
                    association.candidate_id, job.*
                FROM collection_job_candidates AS association
                JOIN collection_jobs AS job ON job.id = association.job_id
                WHERE association.candidate_id = ANY(%s)
                ORDER BY association.candidate_id, job.id DESC
                """,
                (accepted_candidate_ids,),
            )
            job_by_candidate = {
                row["candidate_id"]: _collection_job_to_dict(row) for row in job_rows
            }
            job_ids = list({job["id"] for job in job_by_candidate.values()})
            observation_rows = await _fetchall(
                connection,
                """
                SELECT DISTINCT collection_job_id, dataset_id FROM dataset_discovery_observations
                WHERE collection_job_id = ANY(%s) ORDER BY dataset_id
                """,
                (job_ids,),
            )
            datasets_by_job: dict[int, list[int]] = {}
            for row in observation_rows:
                datasets_by_job.setdefault(row["collection_job_id"], []).append(row["dataset_id"])
            unassociated_candidate_ids = [
                candidate["id"]
                for candidate in candidates
                if candidate["id"] in accepted_candidate_ids
                and candidate["id"] not in job_by_candidate
            ]
            existing_dataset_rows = await _fetchall(
                connection,
                """
                SELECT candidate.id AS candidate_id, dataset.id AS dataset_id
                FROM repository_candidates AS candidate
                JOIN collected_datasets AS dataset ON dataset.dataset_url = candidate.url
                WHERE candidate.id = ANY(%s)
                UNION
                SELECT candidate.id AS candidate_id, observation.dataset_id
                FROM repository_candidates AS candidate
                JOIN dataset_discovery_observations AS observation
                    ON observation.source_url = candidate.url
                WHERE candidate.id = ANY(%s)
                ORDER BY dataset_id
                """,
                (unassociated_candidate_ids, unassociated_candidate_ids),
            )
            datasets_by_candidate: dict[UUID, list[int]] = {}
            for row in existing_dataset_rows:
                datasets_by_candidate.setdefault(row["candidate_id"], []).append(row["dataset_id"])
            collections: dict[UUID, CollectionJobReservation] = {}
            for candidate_id in accepted_candidate_ids:
                job = job_by_candidate.get(candidate_id)
                dataset_ids = (
                    datasets_by_job.get(job["id"], [])
                    if job
                    else datasets_by_candidate.get(candidate_id, [])
                )
                if job:
                    job["dataset_ids"] = dataset_ids
                collections[candidate_id] = CollectionJobReservation(
                    job=job,
                    created=False,
                    already_collected=bool(dataset_ids) if job is None else False,
                    dataset_ids=tuple(dataset_ids),
                )
            return search, candidates, collections
