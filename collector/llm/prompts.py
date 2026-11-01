"""Shared construction of Chat Completions messages and JSON schema instructions."""

from __future__ import annotations

import json


def _build_chat_completions_request_body(
    payload: dict[str, object],
    model: str,
    *,
    system_prompt: str,
    schema: dict[str, object],
) -> dict[str, object]:
    schema_instruction = (
        "Return only one valid JSON object matching this JSON Schema exactly: "
        f"{json.dumps(schema, ensure_ascii=True, separators=(',', ':'))}"
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": f"{system_prompt}\n\n{schema_instruction}",
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=True),
            },
        ],
        "response_format": {"type": "json_object"},
    }
