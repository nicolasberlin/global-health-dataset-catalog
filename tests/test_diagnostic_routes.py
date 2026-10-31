"""Pagination is validated at the diagnostic boundary and keeps owner scope."""

from __future__ import annotations

import pytest
from app.api.presenters.collection import build_collection_job_view

pytestmark = pytest.mark.anyio


def test_job_presenter_filters_legacy_observation_and_coverage_fields():
    job = {
        "id": 1,
        "source_url": "https://example.org/data",
        "status": "error",
        "saved_count": 0,
        "method_attempts": [
            {
                "method": "datacite",
                "code": "repository_http_error",
                "body": "private-provider-body",
                "reason": "private-provider-error",
            }
        ],
        "coverage": {"checked": 1, "private": "private-provider-config"},
    }
    result = build_collection_job_view(job)
    assert result.coverage == {"checked": 1}
    assert "private-provider" not in result.model_dump_json()
    assert result.method_attempts[0]["method"] == "datacite"
