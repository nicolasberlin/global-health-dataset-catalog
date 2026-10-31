"""Export saved search, classification and collection diagnostics for their owner.

The Python client requests this report after progress no longer requires polling.
History is bounded and can be partial; this read never reruns a processing stage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.search_progress import load_search_progress
from app.auth.security import APIPrincipal, require_api_principal
from app.db.classification.voting.history import read_candidate_vote_history
from app.db.collection.traces.reading import read_collection_trace

router = APIRouter(tags=["collector"])


@router.get("/searches/{search_id}/diagnostics")
async def get_search_diagnostics(
    search_id: UUID,
    principal: Annotated[APIPrincipal, Depends(require_api_principal)],
    response: Response,
):
    """Assemble the diagnostic report for GET /collector/searches/{search_id}/diagnostics.

    load_search_progress() verifies ownership and provides the current summary. Add
    saved collection traces and candidate vote history, keeping each read scoped
    to the same owner. Return a dictionary that FastAPI serializes as JSON.
    """
    progress = await load_search_progress(search_id, principal.owner_id)
    response.headers["Cache-Control"] = "no-store"
    job_ids = {
        item.automatic_collection.job.id
        for item in progress.items
        if item.automatic_collection and item.automatic_collection.job
    }
    traces = [await read_collection_trace(job_id, principal.owner_id) for job_id in sorted(job_ids)]
    return {
        "schema_version": "1.0",
        "document_type": "search_diagnostic_trace",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "is_template": False,
        "context": {
            "search_id": str(search_id),
            "query": progress.query,
            "attempt": progress.attempt,
        },
        "summary": progress.model_dump(mode="json"),
        "collections": traces,
        "repository_classifications": [
            {
                "candidate_id": str(item.candidate_id),
                "classification_history": await read_candidate_vote_history(
                    item.candidate_id, principal.owner_id
                ),
            }
            for item in progress.items
        ],
        "export": {
            "method": "persisted_api",
            "coverage": "partial",
            "missing_evidence": [
                "Persisted history can be partial; missing evidence cannot be reconstructed.",
                "Search exports contain bounded history pages and can omit older entries.",
                "Raw pages, invalid model bodies and cookies are not exported.",
            ],
        },
    }
