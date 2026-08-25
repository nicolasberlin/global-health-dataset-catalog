from __future__ import annotations

import json
from datetime import datetime

from psycopg.types.json import Jsonb


class StoredJSONError(ValueError):
    pass


class StoredTimestampError(ValueError):
    pass


def _serialize_discovery_methods(discovery_methods: tuple[str, ...]) -> Jsonb:
    return _jsonb(list(discovery_methods))


def _deserialize_discovery_methods(value: object) -> list[str]:
    if isinstance(value, list):
        data = value
    elif isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exception:
            raise StoredJSONError(
                "Invalid JSON in stored discovery methods field "
                "collection_jobs.discovery_methods."
            ) from exception
    else:
        data = value

    if not isinstance(data, list):
        raise StoredJSONError(
            "Invalid JSON type in stored discovery methods field "
            "collection_jobs.discovery_methods: expected list, "
            f"got {type(data).__name__}."
        )

    invalid_indexes = [
        index for index, item in enumerate(data) if not isinstance(item, str)
    ]
    if invalid_indexes:
        raise StoredJSONError(
            "Invalid JSON items in stored discovery methods field "
            "collection_jobs.discovery_methods at indexes: "
            f"{invalid_indexes}."
        )

    return data


def _serialize_signals(signals: dict[str, object]) -> Jsonb:
    return _jsonb(signals)


def _deserialize_signals(
    value: object,
    field_name: str = "signals",
) -> dict[str, object]:
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exception:
            raise StoredJSONError(
                f"Invalid JSON in stored signals field {field_name}: "
                f"{exception.msg} at line {exception.lineno}, column {exception.colno}."
            ) from exception
    else:
        data = value

    if not isinstance(data, dict):
        raise StoredJSONError(
            f"Invalid JSON type in stored signals field {field_name}: "
            f"expected object, got {type(data).__name__}."
        )

    return data


def _jsonb(value: object) -> Jsonb:
    json.dumps(value, sort_keys=True)
    return Jsonb(value, dumps=_json_dumps)


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _format_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise StoredTimestampError(
                "Invalid timestamp value from database: expected timezone-aware "
                "datetime, got naive datetime."
            )
        return value.isoformat()

    raise StoredTimestampError(
        "Invalid timestamp value from database: expected datetime, "
        f"got {type(value).__name__}."
    )


def _format_optional_timestamp(value: object) -> str:
    if value is None:
        return ""
    return _format_timestamp(value)
