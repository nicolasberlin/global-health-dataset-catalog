from __future__ import annotations

import json

import pytest

from collector.classification.ensemble import EnsemblePageClassifier
from collector.classification.factory import build_default_page_classifier
from collector.classification.llm import (
    HTTPJSONLLMClient,
    LLMPageClassifier,
    LLMProviderConfig,
    openai_responses_provider_config,
)
from collector.classification.page import PageClassificationError
from collector.config import CollectorConfig
from collector.extraction.dataset_metadata import DATASET_METADATA_KEYS
from collector.storage.models import DistributionCandidate, PageSnapshot


def test_llm_page_classifier_returns_validated_classification():
    class FakeClient:
        def __init__(self):
            self.payload = {}

        def classify_page(self, payload):
            self.payload = payload
            return _valid_llm_response()

    client = FakeClient()
    classifier = LLMPageClassifier(client)

    classification = classifier.classify(_page(), [_distribution()])

    assert client.payload["page"]["canonical_url"] == "https://example.org/datasets/mortality"
    assert "geography" not in client.payload["page"]
    assert "date_of_publication" not in client.payload["page"]
    assert "dataset_url" not in client.payload["page"]
    assert tuple(client.payload["page"]["metadata"]) == DATASET_METADATA_KEYS
    assert client.payload["page"]["metadata"] == {
        "Title": "Mortality health dataset",
        "Geography": "France",
        "Date of publication": "2025",
        "Dataset URL": "https://example.org/datasets/mortality",
        "Disease(s)": "malaria",
        "Size of dataset": "12,000 records",
        "Demographic information": "age, sex",
        "Sharing license": "CC-BY-4.0",
        "Modality of data": "tabular",
        "Description of dataset": "Official mortality and epidemiology data.",
    }
    assert client.payload["distributions"][0]["format"] == "CSV"
    assert classification.accepted is True
    assert classification.dataset_probability == 0.91
    assert classification.health_probability == 0.84
    assert classification.health_label == "HEALTH"
    assert classification.dataset_signals == {
        "reason": "The page describes an individual downloadable dataset.",
        "evidence": "The title and CSV distribution indicate dataset access.",
    }


def test_default_page_classifier_is_ensemble_page_classifier(monkeypatch):
    _configure_classifier_models(monkeypatch)

    classifier = build_default_page_classifier()

    assert isinstance(classifier, EnsemblePageClassifier)
    assert classifier.voter_ids == (
        "openai_primary",
        "openai_secondary",
        "openai_tertiary",
    )
    assert classifier.votes_required == 2
    assert classifier.minimum_successful_votes == 2


def test_default_page_classifier_requires_three_distinct_models(monkeypatch):
    monkeypatch.delenv("OPENAI_CLASSIFIER_MODEL_1", raising=False)
    monkeypatch.delenv("OPENAI_CLASSIFIER_MODEL_2", raising=False)
    monkeypatch.delenv("OPENAI_CLASSIFIER_MODEL_3", raising=False)

    with pytest.raises(PageClassificationError, match="must be configured"):
        build_default_page_classifier()

    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_1", "same-model")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_2", "same-model")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_3", "other-model")

    with pytest.raises(PageClassificationError, match="must be distinct"):
        build_default_page_classifier()


def test_llm_page_classifier_derives_accepted_from_config_thresholds():
    class FakeClient:
        def classify_page(self, payload):
            response = _valid_llm_response()
            response["accepted"] = True
            response["dataset_probability"] = 0.59
            response["health_probability"] = 0.34
            return response

    classifier = LLMPageClassifier(
        FakeClient(),
        config=CollectorConfig(min_dataset_probability=0.6, min_health_probability=0.35),
    )

    classification = classifier.classify(_page(), [_distribution()])

    assert classification.accepted is False
    assert classification.dataset_probability == 0.59
    assert classification.health_probability == 0.34


def test_llm_page_classifier_rejects_bool_probability():
    class FakeClient:
        def classify_page(self, payload):
            response = _valid_llm_response()
            response["dataset_probability"] = True
            return response

    classifier = LLMPageClassifier(FakeClient())

    with pytest.raises(PageClassificationError, match="dataset_probability"):
        classifier.classify(_page(), [_distribution()])


def test_llm_page_classifier_rejects_invalid_health_label():
    class FakeClient:
        def classify_page(self, payload):
            response = _valid_llm_response()
            response["health_label"] = "MAYBE_HEALTH"
            return response

    classifier = LLMPageClassifier(FakeClient())

    with pytest.raises(PageClassificationError, match="health_label"):
        classifier.classify(_page(), [_distribution()])


def test_llm_page_classifier_wraps_client_failures():
    class FailingClient:
        def classify_page(self, payload):
            raise TimeoutError("timed out")

    classifier = LLMPageClassifier(FailingClient())

    with pytest.raises(PageClassificationError, match="LLM page classification failed"):
        classifier.classify(_page(), [_distribution()])


def test_http_json_llm_client_uses_provider_config():
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "output_text": json.dumps(_valid_llm_response()),
                }
            ).encode("utf-8")

    def fake_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    provider = LLMProviderConfig(
        name="FakeProvider",
        endpoint_url="https://llm.example.org/classify",
        api_key_env_var="FAKE_LLM_API_KEY",
        model_env_var="FAKE_LLM_MODEL",
        default_model="fake-default-model",
        request_body_builder=_fake_request_body,
        response_text_extractor=_fake_response_text,
    )
    client = HTTPJSONLLMClient(
        provider=provider,
        api_key="test-key",
        model="test-model",
        timeout_seconds=12.0,
        request=fake_request,
    )

    result = client.classify_page({"page": {"title": "Mortality dataset"}})

    body = json.loads(captured["request"].data.decode("utf-8"))
    assert result["dataset_probability"] == 0.91
    assert captured["timeout"] == 12.0
    assert captured["request"].get_header("Authorization") == "Bearer test-key"
    assert captured["request"].full_url == "https://llm.example.org/classify"
    assert body["model"] == "test-model"
    assert body["classification_payload"] == {"page": {"title": "Mortality dataset"}}


def test_openai_provider_config_builds_structured_output_request():
    provider = openai_responses_provider_config()

    body = provider.request_body_builder(
        {"page": {"title": "Mortality dataset"}},
        "test-model",
    )

    assert provider.name == "OpenAI"
    assert provider.api_key_env_var == "OPENAI_API_KEY"
    assert provider.model_env_var == "OPENAI_MODEL"
    assert body["model"] == "test-model"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert "accepted" not in body["text"]["format"]["schema"]["properties"]
    assert "accepted" not in body["text"]["format"]["schema"]["required"]
    assert "metadata object as the primary evidence" in body["input"][0]["content"][0]["text"]


def test_http_json_llm_client_requires_configured_api_key(monkeypatch):
    monkeypatch.delenv("FAKE_LLM_API_KEY", raising=False)
    client = HTTPJSONLLMClient(
        provider=LLMProviderConfig(
            name="FakeProvider",
            endpoint_url="https://llm.example.org/classify",
            api_key_env_var="FAKE_LLM_API_KEY",
            model_env_var="FAKE_LLM_MODEL",
            default_model="fake-default-model",
            request_body_builder=_fake_request_body,
            response_text_extractor=_fake_response_text,
        ),
        api_key="",
    )

    with pytest.raises(PageClassificationError, match="FAKE_LLM_API_KEY"):
        client.classify_page({"page": {"title": "Mortality dataset"}})


def _page() -> PageSnapshot:
    return PageSnapshot(
        url="https://example.org/datasets/mortality",
        canonical_url="https://example.org/datasets/mortality",
        title="Mortality health dataset",
        h1="Mortality health dataset",
        meta_description="Official mortality and epidemiology data.",
        publisher="National Health Agency",
        text="Download CSV data for mortality indicators.",
        geography=("France",),
        date_of_publication="2025",
        dataset_url="https://example.org/datasets/mortality",
        diseases=("malaria",),
        size_of_dataset="12,000 records",
        demographic_information=("age", "sex"),
        sharing_license="CC-BY-4.0",
        modality_of_data=("tabular",),
        description_of_dataset="Official mortality and epidemiology data.",
    )


def _distribution() -> DistributionCandidate:
    return DistributionCandidate(
        url="https://example.org/files/mortality.csv",
        format="CSV",
        probability=0.95,
        anchor="Download CSV",
        mime_type="text/csv",
    )


def _valid_llm_response() -> dict[str, object]:
    return {
        "dataset_probability": 0.91,
        "health_probability": 0.84,
        "health_label": "HEALTH",
        "dataset_signals": {
            "reason": "The page describes an individual downloadable dataset.",
            "evidence": "The title and CSV distribution indicate dataset access.",
        },
        "health_signals": {
            "reason": "The topic is health-related.",
            "evidence": "The page mentions mortality and epidemiology.",
        },
    }


def _fake_request_body(payload: dict[str, object], model: str) -> dict[str, object]:
    return {
        "model": model,
        "classification_payload": payload,
    }


def _fake_response_text(response_payload: object) -> str:
    if not isinstance(response_payload, dict):
        raise PageClassificationError("FakeProvider response must be a JSON object.")
    output_text = response_payload.get("output_text")
    if not isinstance(output_text, str):
        raise PageClassificationError("FakeProvider response did not include output_text.")
    return output_text


def _configure_classifier_models(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_1", "model-a")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_2", "model-b")
    monkeypatch.setenv("OPENAI_CLASSIFIER_MODEL_3", "model-c")
