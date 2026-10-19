import copy
import json
from uuid import UUID

import pytest

from search_lab.backend.comparison import compare
from search_lab.backend.snapshots import Snapshots


def observation(saved=0):
    return {
        "trace": {
            "context": {"search_id": "s1", "query": "HIV"},
            "summary": {
                "items": [
                    {
                        "candidate_id": "c1",
                        "url": "https://example.org/file",
                        "title": "Survey",
                        "classification_status": "accepted",
                        "automatic_collection": {
                            "job": {
                                "id": 44,
                                "outcome": "results" if saved else "incomplete",
                                "saved_count": saved,
                                "errors": [],
                            }
                        },
                    },
                ]
            },
        },
        "attempts": [],
    }


def test_capture_is_private_append_only_and_owner_scoped(tmp_path):
    store = Snapshots(tmp_path)
    one = store.create("alice", observation(), {"label": "Before"})
    two = store.create("alice", observation(1), {"label": "After"})
    assert one["id"] != two["id"]
    assert len(store.list("alice")) == 2 and not store.list("bob")
    assert store.read("alice", UUID(one["id"])) == one
    with pytest.raises(FileNotFoundError):
        store.read("bob", UUID(one["id"]))
    path = store.owner_directory("alice") / (one["id"] + ".json")
    assert path.stat().st_mode & 0o777 == 0o600
    modified = copy.deepcopy(one)
    modified["notes"]["label"] = "Changed"
    path.write_text(json.dumps(modified))
    with pytest.raises(ValueError, match="modified"):
        store.read("alice", one["id"])
    assert len(store.list("alice")) == 1
    with pytest.raises(ValueError):
        store.read("alice", "../bob/file")


def test_collision_does_not_delete_original_evidence(tmp_path, monkeypatch):
    store = Snapshots(tmp_path)
    one = store.create("alice", observation(), {})
    monkeypatch.setattr("search_lab.backend.snapshots.uuid4", lambda: UUID(one["id"]))
    with pytest.raises(FileExistsError):
        store.create("alice", observation(1), {})
    assert store.read("alice", one["id"])["observation"] == observation()


def test_comparison_preserves_missing_values_and_scientific_limits(tmp_path):
    store = Snapshots(tmp_path)
    one = store.create("alice", observation(), {}, candidate_id="c1")
    two = store.create("alice", observation(1), {}, candidate_id="c1")
    result = compare(one, two)
    assert result["items"][0]["before"]["saved_count"] == 0
    assert result["items"][0]["after"]["saved_count"] == 1
    assert result["before"]["collector_version"] is None
    assert any("causal" in text for text in result["warnings"])


def test_candidate_capture_excludes_other_candidates_and_global_errors(tmp_path):
    store = Snapshots(tmp_path)
    data = observation()
    data["trace"]["summary"]["errors"] = [{"code": "global_error"}]
    other = copy.deepcopy(data["trace"]["summary"]["items"][0])
    other.update(candidate_id="c2", url="https://example.org/other", title="Other")
    other["automatic_collection"]["job"]["id"] = 45
    data["trace"]["summary"]["items"].append(other)
    data["trace"]["collections"] = [{"job_id": 44}, {"job_id": 45}]
    data["trace"]["repository_classifications"] = [{"candidate_id": "c1"}, {"candidate_id": "c2"}]
    data["attempts"] = [{"job_id": 44}, {"job_id": 45}]
    snapshot = store.create("alice", data, {}, candidate_id="c1")
    assert snapshot["scope"] == "candidate"
    assert snapshot["candidate"]["title"] == "Survey"
    assert len(snapshot["observation"]["trace"]["summary"]["items"]) == 1
    assert "global_error" not in json.dumps(snapshot)
    assert "Other" not in json.dumps(snapshot)
    assert snapshot["observation"]["attempts"] == [{"job_id": 44}]
    assert snapshot["observation"]["trace"]["collections"] == [{"job_id": 44}]
    assert snapshot["observation"]["trace"]["repository_classifications"] == [
        {"candidate_id": "c1"}
    ]
    assert len(data["trace"]["summary"]["items"]) == 2
    with pytest.raises(ValueError, match="not found"):
        store.create("alice", data, {}, candidate_id="missing")
    legacy = store.create("alice", data, {})
    with pytest.raises(ValueError, match="two candidate"):
        compare(legacy, snapshot)
    other_snapshot = store.create("alice", data, {}, candidate_id="c2")
    with pytest.raises(ValueError, match="same candidate"):
        compare(snapshot, other_snapshot)
    assert any(item["scope"] == "search" for item in store.list("alice"))
