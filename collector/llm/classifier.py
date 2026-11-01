"""Shared LLM invocation and error handling for feature-specific classifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from collector.diagnostics import PipelineFailure
from collector.llm.client import LLMClassificationClient
from collector.llm.errors import ClassificationError

ResultT = TypeVar("ResultT")


class BaseLLMClassifier(Generic[ResultT], ABC):
    """Invoke a client while leaving payload construction and response parsing to features."""

    def __init__(self, client: LLMClassificationClient) -> None:
        self._client = client

    @property
    @abstractmethod
    def failure_message(self) -> str:
        """Message used only when the client raises an unexpected exception."""

    def _classify_payload(self, payload: dict[str, object]) -> ResultT:
        try:
            raw_classification = self._client.classify_payload(payload)
        except PipelineFailure:
            raise
        except Exception as exception:
            raise ClassificationError(
                self.failure_message, code="processing_failed"
            ) from exception

        # Parser errors keep their own diagnostics and are never wrapped as client failures.
        return self._parse_response(raw_classification)

    @abstractmethod
    def _parse_response(self, response: dict[str, object]) -> ResultT:
        """Validate a feature-specific response and return its classification model."""
