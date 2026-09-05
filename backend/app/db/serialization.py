from __future__ import annotations

import json
from datetime import datetime

from psycopg.types.json import Jsonb


class StoredJSONError(ValueError):
    pass


class StoredTimestampError(ValueError):
    pass


def _serialize_discovery_methods(discovery_methods: tuple[str, ...]) -> Jsonb:
    return _jsonb(
        _normalize_string_items_for_storage(
            discovery_methods,
            "discovery method",
        )
    )


def _deserialize_discovery_methods(value: object) -> list[str]:
    data = _deserialize_json_array(
        value,
        "collection_jobs.discovery_methods",
        "discovery methods",
    )
    return _normalize_string_items_from_storage(
        data,
        "collection_jobs.discovery_methods",
        "discovery methods",
    )


def _serialize_geography(geography: tuple[str, ...]) -> Jsonb:
    return _jsonb(
        _normalize_string_items_for_storage(
            geography,
            "geography",
        )
    )


def _deserialize_geography(value: object) -> list[str]:
    data = _deserialize_json_array(
        value,
        "collected_datasets.geography",
        "geography",
    )
    return _normalize_string_items_from_storage(
        data,
        "collected_datasets.geography",
        "geography",
    )


def _serialize_signals(signals: dict[str, object]) -> Jsonb:
    if not isinstance(signals, dict):
        raise StoredJSONError(
            "Invalid signals before storage: expected object, "
            f"got {type(signals).__name__}."
        )

    _assert_json_object_keys_are_strings(signals, "signals")

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
    try:
        _json_dumps(value)
    except (TypeError, ValueError) as exception:
        raise StoredJSONError("Value is not JSON serializable for storage.") from exception

    return Jsonb(value, dumps=_json_dumps)


def _json_dumps(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True)


def _deserialize_json_array(
    value: object,
    field_name: str,
    field_label: str,
) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exception:
            raise StoredJSONError(
                f"Invalid JSON in stored {field_label} field {field_name}."
            ) from exception
    else:
        data = value

    if not isinstance(data, list):
        raise StoredJSONError(
            f"Invalid JSON type in stored {field_label} field {field_name}: "
            f"expected list, got {type(data).__name__}."
        )

    return data


def _normalize_string_items_for_storage(
    value: tuple[str, ...],
    item_label: str,
) -> list[str]:
    if not isinstance(value, tuple):
        raise StoredJSONError(
            f"Invalid {item_label} collection before storage: expected tuple, "
            f"got {type(value).__name__}."
        )

    return _normalize_string_items(
        list(value),
        f"Invalid {item_label} items before storage",
    )


def _normalize_string_items_from_storage(
    value: list[object],
    field_name: str,
    field_label: str,
) -> list[str]:
    return _normalize_string_items(
        value,
        f"Invalid JSON items in stored {field_label} field {field_name}",
    )


def _normalize_string_items(
    value: list[object],
    error_prefix: str,
) -> list[str]:
    normalized_items: list[str] = []
    invalid_indexes: list[int] = []
    blank_indexes: list[int] = []

    for index, item in enumerate(value):
        if not isinstance(item, str):
            invalid_indexes.append(index)
            continue

        normalized_item = item.strip()
        if not normalized_item:
            blank_indexes.append(index)
            continue

        normalized_items.append(normalized_item)

    if invalid_indexes:
        raise StoredJSONError(f"{error_prefix} at indexes: {invalid_indexes}.")
    if blank_indexes:
        raise StoredJSONError(
            f"{error_prefix} with blank values at indexes: {blank_indexes}."
        )

    return list(dict.fromkeys(normalized_items))


def _assert_json_object_keys_are_strings(value: object, path: str) -> None:
    if isinstance(value, dict):
        invalid_keys = [key for key in value if not isinstance(key, str)]
        if invalid_keys:
            raise StoredJSONError(
                "Invalid signal keys before storage: expected string keys at "
                f"{path}, got {invalid_keys!r}."
            )

        for key, nested_value in value.items():
            _assert_json_object_keys_are_strings(nested_value, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_object_keys_are_strings(item, f"{path}[{index}]")


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
