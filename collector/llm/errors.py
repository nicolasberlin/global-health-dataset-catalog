"""Classification failures shared by both domains and the LLM transport."""

from collector.diagnostics import Diagnostic, PipelineFailure


class ClassificationError(PipelineFailure):
    """Raised when LLM classification or its voting process cannot complete successfully."""

    def __init__(
        self,
        message: str,
        *,
        code="processing_failed",
        recovery="manual",
        retry_at=None,
        diagnostics=None,
    ):
        super().__init__(
            message,
            diagnostics=diagnostics
            or [
                Diagnostic(code, "classification", recovery=recovery, retry_at=retry_at),
            ],
        )
