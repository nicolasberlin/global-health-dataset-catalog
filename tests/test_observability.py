"""Operational logs remain useful without retaining sensitive application content."""

import json
import logging
from io import BytesIO
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest
from app import workers

from collector import observability
from collector.classification.llm_client import HTTPJSONLLMClient, LLMProviderConfig
from collector.classification.page import PageClassificationError
from collector.classification.voting import run_voters


@pytest.fixture
def events(caplog, monkeypatch):
    monkeypatch.setattr(observability.logger, "propagate", True)
    caplog.set_level(logging.INFO, logger="collector.operations")
    return lambda: [json.loads(record.message) for record in caplog.records
                    if record.name == "collector.operations"]


def client(request):
    return HTTPJSONLLMClient(
        LLMProviderConfig(
            name="secret-provider", endpoint_url="https://example.org/secret-endpoint",
            api_key_env_var="TEST_OPERATION_API_KEY", model_env_var="TEST_OPERATION_MODEL",
            default_model="secret-model", request_body_builder=lambda payload, model: payload,
            response_text_extractor=lambda payload: payload["output"],
        ),
        api_key="secret-api-key", request=request,
    )


@pytest.mark.parametrize("outcome", [
    "success", "timeout", "http_error", "network_error", "invalid_response",
    "configuration_error",
])
def test_provider_events_measure_and_redact(outcome, events, caplog, monkeypatch):
    clock = iter([10.0, 12.5])
    monkeypatch.setattr(observability, "monotonic", lambda: next(clock))
    errors = {
        "timeout": URLError(TimeoutError("secret-timeout")),
        "http_error": HTTPError("https://secret-url", 500, "secret-error", {},
                                BytesIO(b"secret-response")),
        "network_error": URLError("secret-network"),
    }
    request = Mock(return_value=BytesIO(
        b"secret-invalid-json" if outcome == "invalid_response"
        else json.dumps({"output": '{"text":"secret-response"}'}).encode(),
    ), side_effect=errors.get(outcome))
    provider = client(request)
    if outcome == "configuration_error":
        provider._api_key = None
        monkeypatch.delenv("TEST_OPERATION_API_KEY", raising=False)
    with observability.operation_context(job_id=12):
        if outcome == "success":
            assert provider.classify_request({"prompt": "secret-prompt"}) == {
                "text": "secret-response",
            }
        else:
            with pytest.raises(PageClassificationError):
                provider.classify_request({"prompt": "secret-prompt"})
    assert events() == [{"event": "provider_request", "outcome": outcome,
                         "job_id": 12, "duration_seconds": 2.5}]
    assert "secret" not in caplog.text


@pytest.mark.anyio
async def test_persistence_retry_recovery_and_failure_events(events, caplog):
    from psycopg import OperationalError

    candidate_id = UUID("00000000-0000-0000-0000-000000000001")
    with observability.operation_context(candidate_id=candidate_id):
        operation = AsyncMock(side_effect=[OperationalError("secret-db"), "saved"])
        assert await workers.persist_with_retry(operation, initial_delay=0) == "saved"
        with pytest.raises(ValueError):
            await workers.persist_with_retry(AsyncMock(side_effect=ValueError("secret-db")))
    records = events()
    assert [(r["event"], r["outcome"]) for r in records] == [
        ("persistence_retry", "retry"), ("persistence_finished", "success"),
        ("persistence_duration", "success"), ("persistence_duration", "failed"),
    ]
    assert records[0]["retry_count"] == records[1]["retry_count"] == 1
    assert all(r["candidate_id"] == str(candidate_id) for r in records)
    assert "secret" not in caplog.text


def test_parallel_votes_carry_context_without_leaking_it(events):
    def classify(_):
        return client(Mock(return_value=BytesIO(b'{"output":"{}"}'))).classify_request({})

    with observability.operation_context(job_id=1):
        run_voters([("one", object()), ("two", object())], classify=classify,
                   make_vote=lambda voter, result: result, handled_errors=(ValueError,))
    with observability.operation_context(job_id=2):
        classify(None)
    classify(None)
    assert [r.get("job_id") for r in events()] == [1, 1, 2, None]


@pytest.mark.anyio
async def test_broken_logging_cannot_fail_model_or_persistence(monkeypatch):
    monkeypatch.setattr(observability.logger, "info", Mock(side_effect=RuntimeError("broken")))
    assert client(Mock(return_value=BytesIO(b'{"output":"{}"}'))).classify_request({}) == {}
    assert await workers.persist_with_retry(AsyncMock(return_value="saved")) == "saved"


def test_logging_configuration_is_idempotent(monkeypatch):
    logger = logging.Logger("isolated-operations")
    monkeypatch.setattr(observability, "logger", logger)
    observability.configure_operational_logging()
    observability.configure_operational_logging()
    assert len(logger.handlers) == 1
    assert logger.level == logging.INFO
    assert logger.propagate is False
