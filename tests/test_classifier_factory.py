"""Exercise the default voters through their HTTP payload and response contracts."""

from __future__ import annotations

import io
import json
import threading
from functools import partial

import pytest

from collector.classification import factory
from collector.classification.llm_client import HTTPJSONLLMClient
from collector.classification.page import PageClassificationError
from collector.classification.providers.epfl_rcp import EPFL_RCP_CHAT_COMPLETIONS_URL
from collector.storage.models import PageSnapshot

MODELS = (
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "EPFLiGHT/Gemma-3-27B-MeditronFO",
    "EPFLiGHT/Apertus-70B-MeditronFO",
)
MODEL_VARIABLES = (
    "RCP_DEEPSEEK_MODEL", "RCP_GEMMA_MEDITRON_MODEL", "RCP_APERTUS_MEDITRON_MODEL"
)
KEY_VARIABLES = (
    "RCP_DEEPSEEK_API_KEY", "RCP_GEMMA_MEDITRON_API_KEY", "RCP_APERTUS_MEDITRON_API_KEY"
)
KEYS = ("test-deepseek-key", "test-gemma-key", "test-apertus-key")
PAGE = PageSnapshot(
    url="https://example.org/dataset",
    canonical_url="https://example.org/dataset",
    title="Infant mortality by country",
    search_query="infant mortality",
)


@pytest.fixture(autouse=True)
def configure_keys(monkeypatch):
    for variable, key in zip(KEY_VARIABLES, KEYS):
        monkeypatch.setenv(variable, key)
    for variable in MODEL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def _response(kind, accepted):
    decision = (
        {"accepted": accepted, "dataset_signals": {"reason": "Test vote", "evidence": "Title"}}
        if kind == "page"
        else {"label": "relevant" if accepted else "not_relevant", "reason": "Test vote",
              "missing_information": []}
    )
    return io.BytesIO(json.dumps({
        "choices": [{"message": {"content": json.dumps(decision)}}]
    }).encode())


def _classify(kind):
    if kind == "page":
        return factory.build_default_page_classifier().classify(PAGE, [])
    return factory.build_default_repository_result_classifier().classify(PAGE)


def _inject_transport(monkeypatch, request):
    monkeypatch.setattr(factory, "HTTPJSONLLMClient", partial(HTTPJSONLLMClient, request=request))


@pytest.mark.parametrize("kind", ["page", "repository"])
@pytest.mark.parametrize("accepted_count", [0, 1, 2, 3])
def test_three_models_run_in_parallel_with_separate_keys_and_majority(
    monkeypatch, kind, accepted_count
):
    calls = {}
    barrier = threading.Barrier(3, timeout=3)

    def request(req, timeout):
        body = json.loads(req.data)
        model = body["model"]
        calls[model] = req
        # A sequential implementation cannot pass this barrier.
        barrier.wait()
        return _response(kind, MODELS.index(model) < accepted_count)

    _inject_transport(monkeypatch, request)
    result = _classify(kind)
    assert result.accepted is (accepted_count >= 2)
    assert set(calls) == set(MODELS)
    for index, model in enumerate(MODELS):
        req = calls[model]
        key = KEYS[index]
        assert req.get_header("Authorization") == f"Bearer {key}"
        assert req.full_url == EPFL_RCP_CHAT_COMPLETIONS_URL
        body = json.loads(req.data)
        assert {k: v for k, v in body.items() if k != "model"} == {
            k: v for k, v in json.loads(calls[MODELS[0]].data).items() if k != "model"
        }
        assert body["response_format"] == {"type": "json_object"}
        system = body["messages"][0]["content"]
        assert ("individual global health dataset" if kind == "page" else
                "user's search query") in system
        assert all(key not in req.data.decode() for key in KEYS)
    summary = result.dataset_signals["ensemble"] if kind == "page" else result.ensemble
    assert summary["successful_votes"] == 3
    assert summary["accepted_votes"] == accepted_count
    assert len(summary["voters"]) == 3


@pytest.mark.parametrize("kind", ["page", "repository"])
def test_each_model_can_be_overridden_independently(monkeypatch, kind):
    overrides = ("test-deepseek", "test-gemma", "test-apertus")
    for variable, value in zip(MODEL_VARIABLES, overrides):
        monkeypatch.setenv(variable, value)
    observed = set()

    def request(req, timeout):
        observed.add(json.loads(req.data)["model"])
        return _response(kind, True)

    _inject_transport(monkeypatch, request)
    assert _classify(kind).accepted
    assert observed == set(overrides)


@pytest.mark.parametrize("kind", ["page", "repository"])
@pytest.mark.parametrize("model_index", [0, 1, 2])
def test_missing_key_never_reuses_another_models_credentials(monkeypatch, kind, model_index):
    monkeypatch.delenv(KEY_VARIABLES[model_index])
    observed = []

    def request(req, timeout):
        observed.append(json.loads(req.data)["model"])
        return _response(kind, True)

    _inject_transport(monkeypatch, request)
    with pytest.raises(PageClassificationError, match=KEY_VARIABLES[model_index]):
        _classify(kind)
    assert set(observed) == set(MODELS) - {MODELS[model_index]}


@pytest.mark.parametrize("kind", ["page", "repository"])
@pytest.mark.parametrize("failure", ["timeout", "malformed"])
@pytest.mark.parametrize("model_index", [0, 1, 2])
def test_failed_model_is_an_error_even_when_other_two_accept(
    monkeypatch, kind, failure, model_index
):
    def request(req, timeout):
        if json.loads(req.data)["model"] == MODELS[model_index]:
            if failure == "timeout":
                raise TimeoutError("test timeout")
            return io.BytesIO(b'{"choices": [{"message": {"content": "not JSON"}}]}')
        return _response(kind, True)

    _inject_transport(monkeypatch, request)
    with pytest.raises(PageClassificationError, match="At least 3 classifier votes"):
        _classify(kind)
