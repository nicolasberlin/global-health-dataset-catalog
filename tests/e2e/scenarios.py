"""Fixed external inputs and independently specified observable search outcomes."""

from __future__ import annotations

PUBLISHER = "Fixture Public Health Institute"
RECORDS = {
    "malaria": {
        "title": "Malaria surveillance dataset",
        "description": "Malaria surveillance case counts in Kenya, 2024 and 2025.",
        "publisher": PUBLISHER,
        "country": "Kenya",
        "csv": "country,year,cases\nKenya,2024,12\nKenya,2025,9\n",
        "page_type": "Dataset",
    },
    "malaria-tanzania": {
        "title": "Malaria surveillance dataset in Tanzania",
        "description": "Malaria surveillance case counts in Tanzania, 2024 and 2025.",
        "publisher": "Fixture Tanzania Health Institute",
        "country": "Tanzania",
        "csv": "country,year,cases\nTanzania,2024,21\nTanzania,2025,15\n",
        "page_type": "Dataset",
    },
    "ocean-salinity": {
        "title": "Ocean salinity measurements",
        "description": "Ocean salinity measurements unrelated to malaria or health.",
        "publisher": "Fixture Ocean Institute",
        "country": "",
        "csv": "ocean,year,salinity\nAtlantic,2024,35\nAtlantic,2025,34\n",
        "page_type": "Dataset",
    },
    "malaria-methodology": {
        "title": "Malaria surveillance methodology",
        "description": "An explanatory article about malaria surveillance with an example CSV.",
        "publisher": PUBLISHER,
        "country": "Kenya",
        "csv": "country,year,cases\nKenya,2024,12\nKenya,2025,9\n",
        "page_type": "Article",
    },
}
for _key, _record in RECORDS.items():
    _record.update(
        url=f"https://fixtures.example/records/{_key}",
        csv_url=f"https://fixtures.example/files/{_key}.csv",
        doi=f"10.1234/{_key}-fixture",
    )

# These expected outputs describe the agreed contract, independently of the API response.
SAVED = {
    "label": "relevant",
    "status": "accepted",
    "collection": {
        "state": "saved",
        "outcome": "results",
        "saved_count": 1,
        "method_status": "succeeded",
        "method_code": "",
        "validation": "available",
        "rejected_count": 0,
        "invalid_distribution_count": 0,
    },
}
REJECTED = {"label": "not_relevant", "status": "rejected", "collection": None}
INELIGIBLE = {
    "label": "relevant",
    "status": "accepted",
    "collection": {
        "state": "empty",
        "outcome": "empty",
        "saved_count": 0,
        "method_status": "rejected",
        "method_code": "page_rejected",
        "validation": None,
        "rejected_count": 1,
        "invalid_distribution_count": 0,
    },
}
CSV_MISSING = {
    "label": "relevant",
    "status": "accepted",
    "collection": {
        "state": "empty",
        "outcome": "incomplete",
        "saved_count": 0,
        "method_status": "inconclusive",
        "method_code": "resource_checks_failed",
        "validation": "unavailable",
        "rejected_count": 0,
        "invalid_distribution_count": 1,
    },
}

SCENARIOS = {
    "success": {
        "responses": {"malaria": {"relevance": "relevant", "eligible": True, "csv_status": 200}},
        "expected": {
            "outcome": "results",
            "saved": ["malaria"],
            "candidates": {"malaria": SAVED},
            "persistence": {
                "candidates": 1,
                "jobs": 1,
                "datasets": 1,
                "distributions": 1,
                "votes": 6,
            },
            "calls": {
                "discovery": 1,
                "relevance": 3,
                "landing": 1,
                "eligibility": 3,
                "csv_head": 1,
                "csv_get": 1,
            },
        },
    },
    "not_relevant": {
        "responses": {"ocean-salinity": {"relevance": "not_relevant"}},
        "expected": {
            "outcome": "empty",
            "saved": [],
            "candidates": {"ocean-salinity": REJECTED},
            "persistence": {
                "candidates": 1,
                "jobs": 0,
                "datasets": 0,
                "distributions": 0,
                "votes": 3,
            },
            "calls": {"discovery": 1, "relevance": 3},
        },
    },
    "minority_vote": {
        "responses": {
            "malaria": {
                "relevance_by_model": {
                    "fixture-deepseek": "relevant",
                    "fixture-gemma": "not_relevant",
                    "fixture-apertus": "not_relevant",
                },
                # Controlled downstream responses also expose an erroneous acceptance.
                # Correct execution must never request them; the journal checks this.
                "eligible": True,
                "csv_status": 200,
            },
        },
        "expected": {
            "outcome": "empty",
            "saved": [],
            "candidates": {
                "malaria": {
                    "label": "not_relevant",
                    "status": "rejected",
                    "accepted_votes": 1,
                    "votes": {
                        "epfl_rcp": "relevant",
                        "epfl_rcp_gemma_meditron": "not_relevant",
                        "epfl_rcp_apertus_meditron": "not_relevant",
                    },
                    "collection": None,
                },
            },
            "persistence": {
                "candidates": 1,
                "jobs": 0,
                "datasets": 0,
                "distributions": 0,
                "votes": 3,
            },
            "calls": {"discovery": 1, "relevance": 3},
        },
    },
    "not_eligible": {
        "responses": {"malaria-methodology": {"relevance": "relevant", "eligible": False}},
        "expected": {
            "outcome": "empty",
            "saved": [],
            "candidates": {"malaria-methodology": INELIGIBLE},
            "persistence": {
                "candidates": 1,
                "jobs": 1,
                "datasets": 0,
                "distributions": 0,
                "votes": 6,
            },
            "calls": {"discovery": 1, "relevance": 3, "landing": 1, "eligibility": 3},
        },
    },
    "csv_404": {
        "responses": {"malaria": {"relevance": "relevant", "eligible": True, "csv_status": 404}},
        "expected": {
            "outcome": "incomplete",
            "saved": [],
            "candidates": {"malaria": CSV_MISSING},
            "persistence": {
                "candidates": 1,
                "jobs": 1,
                "datasets": 0,
                "distributions": 0,
                "votes": 6,
            },
            "calls": {
                "discovery": 1,
                "relevance": 3,
                "landing": 1,
                "eligibility": 3,
                "csv_head": 1,
            },
        },
    },
    "multiple_candidates": {
        "responses": {
            "malaria": {"relevance": "relevant", "eligible": True, "csv_status": 200},
            "malaria-tanzania": {"relevance": "relevant", "eligible": True, "csv_status": 200},
            "ocean-salinity": {"relevance": "not_relevant"},
        },
        "expected": {
            "outcome": "results",
            "saved": ["malaria", "malaria-tanzania"],
            "candidates": {"malaria": SAVED, "malaria-tanzania": SAVED, "ocean-salinity": REJECTED},
            "persistence": {
                "candidates": 3,
                "jobs": 2,
                "datasets": 2,
                "distributions": 2,
                "votes": 15,
            },
            "calls": {
                "discovery": 1,
                "relevance": 9,
                "landing": 2,
                "eligibility": 6,
                "csv_head": 2,
                "csv_get": 2,
            },
        },
    },
}
