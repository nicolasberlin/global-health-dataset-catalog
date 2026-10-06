"""Public conclusions depend on evidence, never on exception wording or counts alone."""

import io
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

import pytest
from app.routes.collector_presenters import public_collection_job
from app.search_outcomes import summarize_search

from collector.classification.llm_client import HTTPJSONLLMClient, LLMProviderConfig
from collector.classification.page import PageClassification, PageClassificationError
from collector.classification.page_llm_classifier import LLMPageClassifier
from collector.diagnostics import Diagnostic, PersistenceFailure, public_diagnostics, retry_after
from collector.discovery.adapters import DiscoveredPage
from collector.fetch import FetchedPage, PageFetchError
from collector.main import collect_source_with_report
from collector.storage.models import DistributionCandidate, ValidationResult

SEARCH = {"status": "completed", "origin": "online", "discovery_complete": True}


def candidate(status, *, collection=None):
    return {"classification_status": status, "automatic_collection": collection}


def collection(execution="finished", outcome="empty", ids=()):
    return {"execution_status": execution, "outcome": outcome, "dataset_ids": list(ids)}


@pytest.mark.parametrize(
    "search,items,execution,outcome,active",
    [
        ({**SEARCH, "status": "running"}, [], "running", None, ["search"]),
        (SEARCH, [], "finished", "empty", []),
        ({**SEARCH, "origin": "database", "local_result_count": 2}, [], "finished", "results", []),
        ({**SEARCH, "origin": "database"}, [], "finished", "incomplete", []),
        ({**SEARCH, "discovery_complete": None}, [], "finished", "incomplete", []),
        ({**SEARCH, "status": "error"}, [], "failed", "incomplete", []),
        (SEARCH, [candidate("queued")], "queued", None, []),
        (SEARCH, [candidate("pending")], "finished", "incomplete", []),
        (SEARCH, [candidate("rejected")], "finished", "empty", []),
        (SEARCH, [candidate("error")], "failed", "incomplete", []),
        (
            SEARCH,
            [candidate("classifying"), candidate("error")],
            "running",
            None,
            ["classification"],
        ),
        (
            SEARCH,
            [candidate("accepted", collection=collection(ids=[42]))],
            "finished",
            "results",
            [],
        ),
        (
            SEARCH,
            [
                candidate("accepted", collection=collection("failed", "incomplete")),
                candidate("rejected"),
            ],
            "finished",
            "incomplete",
            [],
        ),
        (
            SEARCH,
            [
                candidate("accepted", collection=collection(outcome="incomplete", ids=[42])),
                candidate("error"),
            ],
            "finished",
            "incomplete",
            [],
        ),
        (
            SEARCH,
            [
                candidate("classifying"),
                candidate("accepted", collection=collection("running", None)),
            ],
            "running",
            None,
            ["classification", "collection"],
        ),
        (
            {
                **SEARCH,
                "status": "partial",
                "errors": [Diagnostic("search_scope_limited", "search", recovery="none").to_dict()],
            },
            [],
            "finished",
            "empty",
            [],
        ),
    ],
)
def test_search_conclusion_table(search, items, execution, outcome, active):
    result = summarize_search(search, items)
    assert (result["execution_status"], result["outcome"]) == (execution, outcome)
    assert result["active_stages"] == active
    assert result["polling_required"] == (execution in {"queued", "running"})


def client(request, api_key="test"):
    return HTTPJSONLLMClient(
        LLMProviderConfig(
            name="test",
            endpoint_url="https://models.example.org/classify",
            api_key_env_var="UNSET_TEST_KEY",
            model_env_var="UNSET_TEST_MODEL",
            default_model="test",
            request_body_builder=lambda payload, model: payload,
            response_text_extractor=lambda body: body["text"],
        ),
        api_key=api_key,
        request=request,
    )


@pytest.mark.parametrize(
    "failure,code,recovery",
    [
        (TimeoutError("private-secret"), "llm_timeout", "manual"),
        (URLError(TimeoutError("private-secret")), "llm_timeout", "manual"),
        (URLError("private-secret"), "llm_network_error", "manual"),
        (
            HTTPError("secret-url", 429, "private-secret", {"Retry-After": "600"}, None),
            "llm_rate_limited",
            "manual",
        ),
        (HTTPError("secret-url", 503, "private-secret", {}, None), "llm_unavailable", "manual"),
        (
            HTTPError("secret-url", 401, "private-secret", {}, None),
            "llm_configuration_error",
            "configuration_required",
        ),
    ],
    ids=["timeout", "url-timeout", "network", "rate-limit", "unavailable", "config"],
)
def test_llm_causes_survive_without_exposing_provider_details(failure, code, recovery):
    def request(*args, **kwargs):
        raise failure

    with pytest.raises(PageClassificationError) as caught:
        client(request).classify_page({})
    error = caught.value.diagnostics[0]
    assert (error.code, error.recovery) == (code, recovery)
    assert "secret" not in str(error.to_dict())
    if code == "llm_rate_limited":
        assert datetime.fromisoformat(error.retry_at) > datetime.now(timezone.utc)


def test_missing_configuration_and_invalid_json_are_distinct(monkeypatch):
    monkeypatch.delenv("UNSET_TEST_KEY", raising=False)
    with pytest.raises(PageClassificationError) as caught:
        client(lambda *a, **k: pytest.fail("must not call provider"), api_key="").classify_page({})
    assert caught.value.diagnostics[0].code == "llm_configuration_error"
    with pytest.raises(PageClassificationError) as caught:
        client(lambda *a, **k: io.BytesIO(b"not json")).classify_page({})
    assert caught.value.diagnostics[0].code == "llm_invalid_response"


def test_retry_after_is_not_shortened_to_an_automatic_budget():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    assert retry_after("600", now=now) == "2026-10-04T00:10:00+00:00"
    assert retry_after("Sun, 04 Oct 2026 00:10:00 GMT", now=now) == retry_after("600", now=now)
    assert retry_after("invalid", now=now) is None


def test_public_diagnostic_rebuilds_message_and_drops_internal_fields():
    raw = {
        **Diagnostic("llm_timeout", "classification").to_dict(),
        "message": "private-secret",
        "traceback": "private-secret",
    }
    public = public_diagnostics([raw])[0]
    assert "secret" not in str(public)
    assert raw["message"] == "private-secret"


def test_persistence_failure_is_not_wrapped_as_a_model_failure():
    class FailingStore:
        def classify_page(self, payload):
            raise PersistenceFailure("SQL private-secret")

    from test_llm_page_classifier import _distribution, _page

    with pytest.raises(PersistenceFailure):
        LLMPageClassifier(FailingStore()).classify(_page(), [_distribution()])


class Accept:
    def classify(self, page, distributions):
        return PageClassification(accepted=True)


def collect(validations):
    links = tuple(
        DistributionCandidate(f"https://example.org/{i}.csv", "CSV", 0.9)
        for i in range(len(validations))
    )
    results = iter(validations)

    def validate(item):
        status = next(results)
        return ValidationResult(
            item.url, item.url, "CSV", status == "available", 200, status=status
        )

    return collect_source_with_report(
        "https://example.org",
        classifier=Accept(),
        discover=lambda _: [
            DiscoveredPage("https://example.org/dataset", "test", distributions=links)
        ],
        validate=validate,
    )


@pytest.mark.parametrize(
    "statuses,complete,saved",
    [
        (["unconfirmed"], False, 0),
        (["restricted"], False, 0),
        (["unavailable"], True, 0),
        (["unconfirmed", "available"], True, 1),
    ],
)
def test_only_failed_necessary_verifications_make_a_collection_incomplete(
    statuses, complete, saved
):
    result = collect(statuses)
    assert result.report.verification_complete == complete
    assert len(result.datasets) == saved
    assert bool(result.report.errors) != complete


def test_captcha_landing_page_cannot_become_empty():
    with pytest.raises(PageFetchError) as caught:
        collect_source_with_report(
            "https://example.org",
            classifier=Accept(),
            discover=lambda _: [DiscoveredPage("https://example.org/dataset", "test")],
            fetch_html=lambda url: FetchedPage(
                url, url, '<html><div class="g-recaptcha"></div></html>', 200, "text/html"
            ),
        )
    assert caught.value.diagnostics[0].code == "verification_unconfirmed"


def test_historical_zero_saved_is_incomplete_and_legacy_contract_survives():
    from test_collector_routes import _collection_job

    job = public_collection_job(_collection_job(status="done"))
    assert job.status == "done" and job.saved_count == 0
    assert job.outcome == "incomplete"
    assert job.errors[0].code == "legacy_unknown"
