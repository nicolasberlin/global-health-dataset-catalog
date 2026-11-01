"""Controlled failures at the untrusted extraction boundary."""

from __future__ import annotations


class ExtractionError(ValueError):
    def __init__(self, reason: str, *, code: str = "extraction_invalid_content") -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
