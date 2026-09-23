"""Optional durable checkpoints for validated, individual model responses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from collector.classification.llm_client import HTTPJSONLLMClient


class VoteStore(Protocol):
    def run(
        self,
        snapshot: dict[str, object],
        voter_id: str,
        invoke: Callable[[], dict[str, object]],
    ) -> dict[str, object]: ...


class CheckpointedLLMClient:
    """Save only domain-valid responses; successful negative votes are reusable too."""

    def __init__(
        self,
        client: HTTPJSONLLMClient,
        store: VoteStore,
        voter_id: str,
        configuration: list[dict[str, object]],
        validate: Callable,
    ) -> None:
        self.client = client
        self.store = store
        self.voter_id = voter_id
        self.configuration = configuration
        self.validate = validate

    def classify_page(self, payload: dict[str, object]) -> dict[str, object]:
        request_body = self.client.prepare_request(payload)

        def invoke():
            result = self.client.classify_request(request_body)
            self.validate(result)
            return result

        result = self.store.run(
            # Bump contract_version when parser semantics change independently of prompts.
            {"contract_version": 1, "configuration": self.configuration, "payload": payload},
            self.voter_id,
            invoke,
        )
        self.validate(result)
        return result
