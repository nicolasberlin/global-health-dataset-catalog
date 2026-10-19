from search_lab.backend.attempts import group_attempts


def test_claims_separate_automatic_attempts_within_the_same_retry_cycle():
    trace = {
        "collections": [
            {
                "job_id": 44,
                "method_attempts": [
                    {"id": "a", "retry_cycle": "same", "sequence": 0, "status": "failed"},
                    {
                        "id": "b",
                        "retry_cycle": "same",
                        "sequence": 0,
                        "status": "succeeded",
                        "checks": [{"status": "available"}],
                    },
                ],
            }
        ]
    }
    groups = group_attempts(trace, {"a": "2026-10-09T10:00:00Z", "b": "2026-10-12T10:00:00Z"})
    assert len(groups) == 2
    assert groups[0]["previous_case_id"] is None
    assert groups[1]["previous_case_id"] == groups[0]["case_id"]
    assert groups[1]["available_checks"] == 1
    assert all(group["collector_version"] is None for group in groups)
    assert "saved_count" not in groups[0]
    assert (
        group_attempts(trace, {"a": "2026-10-09T10:00:00Z", "b": "2026-10-12T10:00:00Z"}) == groups
    )


def test_missing_claim_evidence_does_not_merge_methods_into_invented_attempt():
    groups = group_attempts(
        {
            "collections": [
                {
                    "job_id": 44,
                    "method_attempts": [
                        {"id": "a", "sequence": 0},
                        {"id": "b", "sequence": 0},
                    ],
                }
            ]
        },
        {},
    )
    assert len(groups) == 2 and all(group["claim_version"] is None for group in groups)
