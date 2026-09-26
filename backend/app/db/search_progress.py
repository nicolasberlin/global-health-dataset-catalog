"""Owner-scoped, consistent snapshots of a search and its existing follow-up."""

from uuid import UUID

from .collection_jobs import CollectionJobReservation, _collection_job_to_dict
from .connection import _fetchall, _fetchone, _require_database_pool
from .repository_candidates import _CANDIDATE_COLUMNS, _repository_candidate_to_dict
from .search_sessions import _normalized_owner_id


async def read_search_progress(search_id: UUID, owner_id: str):
    async with _require_database_pool().connection() as connection:
        async with connection.transaction():
            await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            search = await _fetchone(connection,
                "SELECT status FROM search_sessions WHERE id = %s AND owner_id = %s",
                (search_id, _normalized_owner_id(owner_id)))
            if search is None:
                return None
            rows = await _fetchall(connection, f"""
                SELECT {_CANDIDATE_COLUMNS} FROM repository_candidates AS candidate
                JOIN search_sessions AS session ON session.id = candidate.search_session_id
                WHERE session.id = %s AND session.owner_id = %s
                ORDER BY candidate.created_at, candidate.id
            """, (search_id, owner_id))
            candidates = [_repository_candidate_to_dict(row) for row in rows]
            accepted_ids = [item["id"] for item in candidates
                            if item["classification_status"] == "accepted"]
            # Preserve the individual read's rule: the latest explicitly associated
            # job wins, even when another job at the same URL has saved data.
            jobs = await _fetchall(connection, """
                SELECT DISTINCT ON (association.candidate_id)
                    association.candidate_id, job.*
                FROM collection_job_candidates AS association
                JOIN collection_jobs AS job ON job.id = association.job_id
                WHERE association.candidate_id = ANY(%s)
                ORDER BY association.candidate_id, job.id DESC
            """, (accepted_ids,))
            job_by_candidate = {row["candidate_id"]: _collection_job_to_dict(row) for row in jobs}
            job_ids = list({job["id"] for job in job_by_candidate.values()})
            observations = await _fetchall(connection, """
                SELECT DISTINCT collection_job_id, dataset_id FROM dataset_discovery_observations
                WHERE collection_job_id = ANY(%s) ORDER BY dataset_id
            """, (job_ids,))
            datasets_by_job = {}
            for row in observations:
                datasets_by_job.setdefault(row["collection_job_id"], []).append(row["dataset_id"])
            unassociated = [item for item in candidates
                            if item["id"] in accepted_ids and item["id"] not in job_by_candidate]
            existing = await _fetchall(connection, """
                SELECT candidate.id AS candidate_id, dataset.id AS dataset_id
                FROM repository_candidates AS candidate
                JOIN collected_datasets AS dataset ON dataset.dataset_url = candidate.url
                    OR EXISTS (SELECT 1 FROM dataset_discovery_observations AS observation
                               WHERE observation.dataset_id = dataset.id
                                 AND observation.source_url = candidate.url)
                WHERE candidate.id = ANY(%s) ORDER BY dataset.id
            """, ([item["id"] for item in unassociated],))
            existing_ids = {}
            for row in existing:
                existing_ids.setdefault(row["candidate_id"], []).append(row["dataset_id"])
            collections = {}
            for candidate_id in accepted_ids:
                job = job_by_candidate.get(candidate_id)
                ids = (datasets_by_job.get(job["id"], []) if job
                       else existing_ids.get(candidate_id, []))
                if job:
                    job["dataset_ids"] = ids
                collections[candidate_id] = CollectionJobReservation(
                    job, False, bool(ids) if job is None else False, tuple(ids),
                )
            return search["status"], candidates, collections
