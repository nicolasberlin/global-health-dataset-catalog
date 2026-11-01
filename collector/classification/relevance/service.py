"""Prepare repository candidate evidence and attach its relevance classification."""

from __future__ import annotations

from dataclasses import replace

from collector.classification.relevance.models import RepositoryResultClassifier
from collector.metadata.dataset import normalize_dataset_metadata
from collector.models import PageSnapshot
from collector.search.models import MISSING_METADATA_VALUE, RepositorySearchResult


def classify_repository_result(
    result: RepositorySearchResult,
    classifier: RepositoryResultClassifier,
) -> RepositorySearchResult:
    """Attach one relevance decision to provider metadata loaded by the caller.

    Acceptance makes the candidate eligible for the normal collection pipeline;
    this function itself never converts or saves it as a ``CollectedDataset``.
    LLM failures propagate as operational errors instead of semantic rejections.
    """

    classification = classifier.classify(_repository_result_page(result))
    return replace(result, classification=classification)


def _repository_result_page(result: RepositorySearchResult) -> PageSnapshot:
    """Adapt provider metadata to the shared classifier evidence contract."""

    metadata = normalize_dataset_metadata(result.metadata)
    title = _metadata_text(metadata["Title"], fallback=result.title)
    description = _metadata_text(
        metadata["Description of dataset"],
        fallback=result.description,
    )
    return PageSnapshot(
        url=result.url,
        canonical_url=result.url,
        search_query=result.search_query,
        title=title,
        meta_description=description,
        publisher=result.publisher,
        geography=_metadata_items(metadata["Geography"]),
        date_of_publication=_metadata_text(
            metadata["Date of publication"],
            fallback=result.date,
        ),
        dataset_url=_metadata_text(metadata["Dataset URL"], fallback=result.url),
        diseases=_metadata_items(metadata["Disease(s)"]),
        size_of_dataset=_metadata_text(metadata["Size of dataset"]),
        demographic_information=_metadata_items(
            metadata["Demographic information"]
        ),
        sharing_license=_metadata_text(metadata["Sharing license"]),
        modality_of_data=_metadata_items(metadata["Modality of data"]),
        description_of_dataset=description,
        text=" ".join(
            value
            for value in (result.title, result.description, " ".join(result.keywords))
            if value
        ),
    )


def _metadata_text(value: str, *, fallback: str = "") -> str:
    return fallback if value == MISSING_METADATA_VALUE else value


def _metadata_items(value: str) -> tuple[str, ...]:
    if value == MISSING_METADATA_VALUE:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())
