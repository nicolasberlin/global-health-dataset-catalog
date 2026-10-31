"""Classification failures shared by both domains and the LLM transport."""

from collector.diagnostics import Diagnostic, PipelineFailure


class PageClassificationError(PipelineFailure):
    """Raised when a page classifier cannot produce a usable classification."""

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
