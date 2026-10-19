from pathlib import Path

import pytest

from search_lab.backend.settings import local_api_url
from search_lab.scenarios.experiment import target_database
from search_lab.scenarios.run import execute, public_evidence


def test_offline_reproduction_uses_real_normalizer_without_inventing_http_status():
    fixture = Path(__file__).parents[1] / "cases/dataverse-file/metadata.json"
    result = execute(
        "api", "https://dataverse.harvard.edu/file.xhtml?fileId=123", offline_json=fixture
    )
    assert result["code"] == "repository_metadata_invalid"
    assert result["http_status"] is None


def test_collection_does_not_call_ai_without_explicit_opt_in():
    with pytest.raises(ValueError, match="include-ai"):
        execute("collection", "https://example.org/data")


@pytest.mark.parametrize(
    "url",
    [
        "https://remote.example",
        "http://user:secret@127.0.0.1:8001",
        "http://127.0.0.1:8001/?token=secret",
        "http://127.0.0.1:8001/path",
    ],
)
def test_lab_upstream_is_not_an_arbitrary_proxy(url):
    with pytest.raises(ValueError):
        local_api_url(url)


def test_experiment_database_never_targets_current_catalog(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/global_health")
    with pytest.raises(ValueError):
        target_database("global_health")
    assert "ghdc_lab_test" in target_database("ghdc_lab_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/ghdc_lab_test")
    with pytest.raises(ValueError):
        target_database("ghdc_lab_test")


def test_reproduction_omits_exception_bodies_and_signed_query_parameters():
    result = public_evidence(
        {
            "validation_failures": [
                {
                    "final_url": "https://example.org/file?X-Amz-Signature=secret&fileId=1",
                    "error": "provider detail with secret",
                    "http_status": 403,
                }
            ]
        }
    )
    assert "secret" not in str(result)
    assert result["validation_failures"][0]["http_status"] == 403
