"""Verify deterministic search outcomes using the real API, workers and HTTP requests."""

from __future__ import annotations

from tests.e2e.support.client import assert_search_submission, get_catalogue_results


def test_search_end_to_end(client, mock_external_services, workflow, scenario):
    # Submit a search through the real HTTP server.
    response = client.post(
        "/collector/searches",
        json={"query": "malaria"},
        headers={"Idempotency-Key": "malaria-e2e"},
    )
    assert response.status_code == 202
    command = assert_search_submission(response)

    # Wait for processing to finish, then check discovery and classification separately.
    progress = workflow.wait_for_search_completion(client, command)
    assert progress["execution_status"] == "finished"
    expected_count = len(scenario["expected"]["candidates"])
    assert len(progress["items"]) == expected_count, (
        f"Expected {expected_count} discovered candidate(s), got {len(progress['items'])}"
    )
    candidates = workflow.assert_candidates(progress)
    assert progress["outcome"] == scenario["expected"]["outcome"]

    # Retrieve the final catalogue through HTTP and check the exact expected results.
    datasets = get_catalogue_results(client, progress["dataset_ids"])
    assert len(datasets) == len(scenario["expected"]["saved"])
    assert {dataset["dataset_url"]: dataset["title"] for dataset in datasets} == {
        scenario["records"][key]["url"]: scenario["records"][key]["title"]
        for key in scenario["expected"]["saved"]
    }

    # Retain detailed checks of worker decisions, validation evidence and persistence.
    workflow.assert_result(client, command, progress, datasets, candidates)
    mock_external_services.assert_expected_calls()
