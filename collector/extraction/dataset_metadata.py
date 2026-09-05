from __future__ import annotations

from collections.abc import Iterable, Mapping

DATASET_METADATA_KEYS = (
    "Title",
    "Geography",
    "Date of publication",
    "Dataset URL",
    "Disease(s)",
    "Size of dataset",
    "Demographic information",
    "Sharing license",
    "Modality of data",
    "Description of dataset",
)
MISSING_DATASET_METADATA_VALUE = "NA"


def empty_dataset_metadata() -> dict[str, str]:
    return build_dataset_metadata()


def normalize_dataset_metadata(
    metadata: Mapping[str, object] | None,
) -> dict[str, str]:
    metadata = metadata or {}
    return {
        key: _value(metadata.get(key, ""))
        for key in DATASET_METADATA_KEYS
    }


def build_dataset_metadata(
    *,
    title: str = "",
    geography: Iterable[str] = (),
    date_of_publication: str = "",
    dataset_url: str = "",
    diseases: Iterable[str] = (),
    size_of_dataset: str = "",
    demographic_information: Iterable[str] = (),
    sharing_license: str = "",
    modality_of_data: Iterable[str] = (),
    description_of_dataset: str = "",
) -> dict[str, str]:
    return normalize_dataset_metadata(
        {
            "Title": title,
            "Geography": _values(geography),
            "Date of publication": date_of_publication,
            "Dataset URL": dataset_url,
            "Disease(s)": _values(diseases),
            "Size of dataset": size_of_dataset,
            "Demographic information": _values(demographic_information),
            "Sharing license": sharing_license,
            "Modality of data": _values(modality_of_data),
            "Description of dataset": description_of_dataset,
        }
    )


def dataset_metadata_text(metadata: Mapping[str, object]) -> str:
    normalized_metadata = normalize_dataset_metadata(metadata)
    return " ".join(
        value
        for key in DATASET_METADATA_KEYS
        if (
            value := normalized_metadata.get(key, "")
        ) and value != MISSING_DATASET_METADATA_VALUE
    )


def _value(value: object) -> str:
    if value is None:
        return MISSING_DATASET_METADATA_VALUE

    normalized_value = str(value).strip()
    return normalized_value if normalized_value else MISSING_DATASET_METADATA_VALUE


def _values(values: Iterable[str]) -> str:
    normalized_values = []
    for value in values:
        normalized_value = value.strip()
        if normalized_value and normalized_value not in normalized_values:
            normalized_values.append(normalized_value)

    return ", ".join(normalized_values) if normalized_values else MISSING_DATASET_METADATA_VALUE
