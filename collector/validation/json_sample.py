"""Read evidence from a truncated JSON prefix without repairing the document.

Only complete array elements and complete record fields count as evidence.
Every sampled token is checked, including the unfinished tail. Unread bytes
cannot establish whole-document validity or rule out a later API error.
"""

from __future__ import annotations

import codecs
import json
import re

_MISSING = object()
_ENVELOPES = {"data", "results", "records", "value", "items", "features"}
_ERROR_FIELDS = {"error", "errors", "success", "status"}
_STRING_PREFIX = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*'
    r'(?:\\(?:u[0-9a-fA-F]{0,3})?)?\Z'
)
_NUMBER_PREFIX = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]*)?(?:[eE][+-]?[0-9]*)?\Z')


def read_json_prefix(sample: bytes) -> object:
    # An incomplete final UTF-8 code point is expected at a byte boundary;
    # invalid encoding elsewhere must still fail.
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    text = decoder.decode(sample, final=False)
    if decoder.getstate()[0]:
        # Preserve its syntactic position: a split code point is legitimate
        # inside an unfinished string, not after a closed document.
        text += "\ufffd"
    reader = _PrefixReader(text)
    value, _ = reader.value(0)
    reader.whitespace()
    if reader.position != len(text):
        raise ValueError("Invalid trailing JSON content.")
    return None if value is _MISSING else value


class _PrefixReader:
    def __init__(self, text: str):
        self.text = text
        self.position = 0
        self.decoder = json.JSONDecoder()

    def whitespace(self) -> None:
        while self.position < len(self.text) and self.text[self.position] in " \r\n\t":
            self.position += 1

    def value(self, depth: int) -> tuple[object, bool]:
        self.whitespace()
        if depth > 64:
            raise ValueError("JSON sample nesting limit exceeded.")
        if self.position == len(self.text):
            return _MISSING, False
        start = self.text[self.position]
        if start in "[{":
            return self.container(depth, start == "{")
        # Numbers at EOF may be unfinished (e.g. 1 followed by an unread exponent).
        if start in "-0123456789" and (
            (start == "-" and self.position + 1 == len(self.text))
            or _NUMBER_PREFIX.fullmatch(self.text, self.position)
        ):
            self.position = len(self.text)
            return _MISSING, False
        try:
            value, end = self.decoder.raw_decode(self.text, self.position)
        except ValueError:
            tail = self.text[self.position:]
            if (_STRING_PREFIX.fullmatch(tail)
                    or any(literal.startswith(tail) for literal in ("true", "false", "null"))):
                self.position = len(self.text)
                return _MISSING, False
            raise
        self.position = end
        return value, True

    def container(self, depth: int, mapping: bool) -> tuple[object, bool]:
        result = {} if mapping else []
        closing = "}" if mapping else "]"
        self.position += 1
        self.whitespace()
        if self.position < len(self.text) and self.text[self.position] == closing:
            self.position += 1
            return result, True
        while True:
            key = None
            if mapping:
                self.whitespace()
                if self.position == len(self.text):
                    return result, False
                if self.text[self.position] != '"':
                    raise ValueError("Expected a JSON object key.")
                key, complete = self.value(depth + 1)
                if not complete:
                    return result, False
                self.whitespace()
                if self.position == len(self.text):
                    if key in _ERROR_FIELDS:
                        raise ValueError("An API error indicator is incomplete.")
                    if key in _ENVELOPES:
                        result[key] = None
                    return result, False
                if self.text[self.position] != ":":
                    raise ValueError("Expected a JSON object colon.")
                self.position += 1
            value, complete = self.value(depth + 1)
            if mapping:
                if not complete and key in _ERROR_FIELDS:
                    raise ValueError("An API error indicator is incomplete.")
                # Only envelopes can contribute incomplete containers: their
                # children have already been filtered to complete evidence.
                if complete or (key in _ENVELOPES and value is not _MISSING):
                    result[key] = value
                elif key in _ENVELOPES:
                    result[key] = None
                else:
                    result.pop(key, None)
            elif complete:
                result.append(value)
            if not complete:
                return result, False
            self.whitespace()
            if self.position == len(self.text):
                return result, False
            separator = self.text[self.position]
            self.position += 1
            if separator == closing:
                return result, True
            if separator != ",":
                raise ValueError("Expected a JSON container separator.")
            # A comma must be followed by another member, never a closing bracket.
