"""HTTP helpers and assertions shared by the end-to-end search scenarios."""

from __future__ import annotations

import json
import time
from collections import Counter
from uuid import UUID

MODELS = {"fixture-deepseek", "fixture-gemma", "fixture-apertus"}
VOTERS = {"epfl_rcp", "epfl_rcp_gemma_meditron", "epfl_rcp_apertus_meditron"}


def request_json(client, path):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.text)
    return response.json(), response.headers


def assert_search_submission(response):
    command = response.json()
    search_id = command["search_id"]
    assert str(UUID(search_id)) == search_id and command["attempt"] == 1
    progress_path = f"/collector/searches/{search_id}/progress"
    assert command["progress_url"] == response.headers["Location"] == progress_path
    assert response.headers["Cache-Control"] == "no-store"
    return command


def get_catalogue_results(client, dataset_ids):
    # With no saved IDs, independently verified empty storage permits an absent-ID read.
    ids = dataset_ids or [2147483647]
    response = client.get(
        "/collector/collected-datasets/by-id", params=[("ids", dataset_id) for dataset_id in ids]
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def diagnostic_codes(errors):
    return [(error["code"], error["stage"]) for error in errors]


class ExternalServiceJournal:
    """Make unexpected calls fail even when a worker catches their exceptions."""

    def __init__(self, scenario, directory):
        self.scenario = scenario
        self.expected = scenario["expected"]
        self.journal = directory / "external-calls.jsonl"
        self.journal.write_text("")
        self.verified = False

    def events(self):
        # Read complete lines only while workers might still be appending an event.
        return [
            json.loads(line)
            for line in self.journal.read_text().splitlines(keepends=True)
            if line.endswith("\n")
        ]

    def assert_no_violations(self):
        violations = [event for event in self.events() if event.get("violation")]
        assert not violations, f"External request violations: {violations}"

    def assert_expected_calls(self, *, log=True):
        journal = self.journal.read_text()
        assert journal.endswith("\n"), "Incomplete external request journal"
        events = [json.loads(line) for line in journal.splitlines()]
        violations = [event for event in events if event.get("violation")]
        assert not violations, f"External request violations: {violations}"
        observed = Counter(
            (event["kind"], event["candidate"], event["model"], event["http_status"])
            for event in events
        )
        expected = Counter({("discovery", None, None, 200): 1})
        for key, spec in self.expected["candidates"].items():
            for model in MODELS:
                expected["relevance", key, model, 200] = 1
            collection = spec["collection"]
            if collection is None:
                continue
            expected["landing", key, None, 200] = 1
            for model in MODELS:
                expected["eligibility", key, model, 200] = 1
            if collection["validation"] == "available":
                expected["csv_head", key, None, 200] = 1
                expected["csv_get", key, None, 200] = 1
            elif collection["validation"] == "unavailable":
                expected["csv_head", key, None, 404] = 1
        assert observed == expected, f"External calls differ: {observed} != {expected}"
        assert Counter(event["kind"] for event in events) == Counter(self.expected["calls"])
        self.verified = True
        if log:
            print("E2E external calls: " + json.dumps(events), flush=True)


class SearchWorkflowChecks:
    """Keep detailed checks behind the test's visible POST, wait and GET steps."""

    def __init__(self, scenario, observer, server, external_services):
        self.scenario = scenario
        self.expected = scenario["expected"]
        self.records = scenario["records"]
        self.observer = observer
        self.server = server
        self.external_services = external_services

    def wait_until(self, check, *, timeout, description):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.server.check_alive()
            self.external_services.assert_no_violations()
            result = check()
            if result:
                return result
            time.sleep(0.1)
        raise AssertionError(f"Timed out waiting for {description}")

    def assert_history(self, history):
        assert history["history_truncated"] is False
        assert len(history["attempts"]) == 3
        assert {attempt["model"] for attempt in history["attempts"]} == MODELS
        assert {attempt["voter_id"] for attempt in history["attempts"]} == VOTERS
        for attempt in history["attempts"]:
            assert attempt["status"] == "succeeded" and attempt["errors"] == []
            assert attempt["attempt"] == 1 and attempt["evidence"] == "live"

    def assert_persistence(self, observer):
        tables = {
            "candidates": "repository_candidates",
            "jobs": "collection_jobs",
            "datasets": "collected_datasets",
            "distributions": "collected_distributions",
            "votes": "classification_votes",
        }
        for name, table in tables.items():
            count = observer.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == self.expected["persistence"][name], (table, count)
        vote_statuses = observer.execute(
            "SELECT DISTINCT status FROM classification_votes"
        ).fetchall()
        assert vote_statuses == [("succeeded",)], vote_statuses

    def assert_candidate(self, candidate, key, expected):
        item = self.records[key]
        for field in ("url", "title", "description", "publisher", "doi"):
            assert candidate[field] == item[field], (key, field, candidate[field])
        assert candidate["classification_status"] == expected["status"]
        decision = candidate["classification"]
        assert decision["relevance_label"] == expected["label"]
        assert decision["accepted"] is (expected["status"] == "accepted")
        assert decision["missing_information"] == []
        ensemble = decision["ensemble"]
        assert ensemble["successful_votes"] == 3 and ensemble["failed_votes"] == 0
        assert ensemble["accepted_votes"] == expected.get(
            "accepted_votes", 3 if decision["accepted"] else 0
        )
        assert len(ensemble["voters"]) == 3
        assert {vote["voter_id"] for vote in ensemble["voters"]} == VOTERS
        expected_labels = expected.get("votes", dict.fromkeys(VOTERS, expected["label"]))
        assert set(expected_labels) == VOTERS
        for vote in ensemble["voters"]:
            label = expected_labels[vote["voter_id"]]
            assert vote["accepted"] is (label in {"relevant", "somewhat_relevant"})
            assert vote["relevance_label"] == label
        assert candidate["errors"] == [] and candidate["classification_error"] == ""
        assert candidate["classification_progress"] == {"total": 3, "succeeded": 3, "failed": 0}
        collection = expected["collection"]
        if collection is None:
            assert candidate["automatic_collection"] is None
            return []
        followup = candidate["automatic_collection"]
        assert followup["state"] == collection["state"]
        assert followup["execution_status"] == "finished"
        assert followup["outcome"] == collection["outcome"]
        wanted_codes = (
            [("verification_unconfirmed", "validation")]
            if (collection["outcome"] == "incomplete")
            else []
        )
        assert diagnostic_codes(followup["errors"]) == wanted_codes
        job = followup["job"]
        assert job["source_url"] == item["url"] and job["kind"] == "repository_candidate"
        assert job["status"] == "done" and job["execution_status"] == "finished"
        assert job["outcome"] == collection["outcome"]
        assert job["saved_count"] == collection["saved_count"]
        assert job["dataset_ids"] == followup["dataset_ids"]
        assert len(job["dataset_ids"]) == collection["saved_count"]
        assert diagnostic_codes(job["errors"]) == wanted_codes
        assert job["error"] == "" and job["error_code"] == ""
        assert job["classification_progress"] == {"total": 3, "succeeded": 3, "failed": 0}
        assert job["accepted_count"] == collection["saved_count"]
        assert job["rejected_count"] == collection["rejected_count"]
        assert job["invalid_distribution_count"] == collection["invalid_distribution_count"]
        return job["dataset_ids"]

    def assert_catalog(self, progress, candidates, datasets):
        by_url = {dataset["dataset_url"]: dataset for dataset in datasets}
        assert {dataset["id"] for dataset in datasets} == set(progress["dataset_ids"])
        for key in self.expected["saved"]:
            item = self.records[key]
            dataset = by_url[item["url"]]
            assert candidates[item["url"]]["automatic_collection"]["dataset_ids"] == [dataset["id"]]
            for field in ("description", "publisher"):
                assert dataset[field] == item[field]
            assert len(dataset["distributions"]) == 1
            distribution = dataset["distributions"][0]
            assert distribution["url"] == item["csv_url"] and distribution["format"] == "CSV"
            assert len(dataset["validation_results"]) == 1
            validation = dataset["validation_results"][0]
            assert validation["url"] == validation["final_url"] == distribution["url"]
            assert validation["ok"] is True and validation["status"] == "available"
            assert validation["format"] == "CSV" and validation["mime_type"] == "text/csv"
            assert validation["http_status"] == 200 and validation["error"] == ""
            assert validation["size_bytes"] == len(item["csv"].encode())
            page_votes = dataset["dataset_signals"]["ensemble"]["voters"]
            assert len(page_votes) == 3 and all(vote["accepted"] for vote in page_votes)

    def assert_diagnostics(self, client, search_id, candidates):
        report, _ = request_json(client, f"/collector/searches/{search_id}/diagnostics")
        assert report["context"]["search_id"] == search_id
        assert report["summary"]["outcome"] == self.expected["outcome"]
        histories = report["repository_classifications"]
        assert {entry["candidate_id"] for entry in histories} == {
            candidate["candidate_id"] for candidate in candidates.values()
        }
        for entry in histories:
            self.assert_history(entry["classification_history"])
        collections = {entry["job_id"]: entry for entry in report["collections"]}
        jobs = [
            candidate["automatic_collection"]["job"]
            for candidate in candidates.values()
            if candidate["automatic_collection"] is not None
        ]
        assert set(collections) == {job["id"] for job in jobs}
        for key, expected in self.expected["candidates"].items():
            spec = expected["collection"]
            if spec is None:
                continue
            job = candidates[self.records[key]["url"]]["automatic_collection"]["job"]
            trace = collections[job["id"]]
            assert trace["history_truncated"] is False and trace["checks_truncated"] is False
            self.assert_history(trace["classification_history"])
            assert len(trace["method_attempts"]) == 1
            method = trace["method_attempts"][0]
            assert method["method"] == "html" and method["status"] == spec["method_status"]
            assert method.get("code", "") == spec["method_code"]
            checks = method["checks"]
            if spec["validation"] is None:
                assert checks == []
            else:
                assert len(checks) == 1
                check = checks[0]
                assert check["url"] == self.records[key]["csv_url"]
                assert check["status"] == spec["validation"]
                assert check["http_status"] == (404 if spec["validation"] == "unavailable" else 200)

    def assert_failed_validation_persisted(self, observer, candidates):
        for key, expected in self.expected["candidates"].items():
            spec = expected["collection"]
            if spec is None:
                continue
            job = candidates[self.records[key]["url"]]["automatic_collection"]["job"]
            failures = observer.execute(
                "SELECT validation_failures FROM collection_jobs WHERE id=%s", (job["id"],)
            ).fetchone()[0]
            if spec["validation"] == "unavailable":
                assert len(failures) == 1
                assert failures[0]["url"] == self.records[key]["csv_url"]
                assert failures[0]["status"] == "unavailable"
                assert failures[0]["http_status"] == 404 and failures[0]["ok"] is False
            else:
                assert failures == []

    def wait_for_search_completion(self, client, command):
        # Termination depends only on the API state, not the expected candidate count.
        def finished():
            progress, headers = request_json(client, command["progress_url"])
            assert headers["Cache-Control"] == "no-store"
            return progress if progress["polling_required"] is False else None

        return self.wait_until(finished, timeout=45, description="final HTTP progress")

    def assert_candidates(self, progress):
        candidates = {item["url"]: item for item in progress["items"]}
        assert set(candidates) == {self.records[key]["url"] for key in self.expected["candidates"]}
        saved_ids = []
        for key, expected in self.expected["candidates"].items():
            candidate = candidates[self.records[key]["url"]]
            assert candidate["search_id"] == progress["search_id"]
            saved_ids.extend(self.assert_candidate(candidate, key, expected))
        assert len(progress["dataset_ids"]) == len(self.expected["saved"])
        assert len(set(saved_ids)) == len(saved_ids)
        assert set(progress["dataset_ids"]) == set(saved_ids)
        return candidates

    def assert_result(self, client, command, progress, datasets, candidates):
        search_id = command["search_id"]
        assert progress["search_id"] == search_id and progress["query"] == "malaria"
        assert progress["origin"] == "online" and progress["attempt"] == 1
        assert progress["local_dataset_ids"] == []
        assert progress["polling_required"] is False and progress["active_stages"] == []
        assert progress["warnings"] == []
        expected_errors = (
            [("verification_unconfirmed", "validation")]
            if (self.expected["outcome"] == "incomplete")
            else []
        )
        assert diagnostic_codes(progress["errors"]) == expected_errors
        self.assert_catalog(progress, candidates, datasets)
        self.assert_diagnostics(client, search_id, candidates)
        self.assert_failed_validation_persisted(self.observer, candidates)
        self.assert_persistence(self.observer)
        self.server.check_alive()
        print(
            "E2E result: "
            + json.dumps(
                {
                    "scenario": self.scenario["name"],
                    "search_id": search_id,
                    "outcome": progress["outcome"],
                    "dataset_ids": progress["dataset_ids"],
                    "candidates": len(progress["items"]),
                }
            ),
            flush=True,
        )
