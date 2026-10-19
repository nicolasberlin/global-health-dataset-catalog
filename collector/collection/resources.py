"""One bounded validation and retention policy for source and record collection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from collector.budget import CollectionBudgetExceeded, check_collection_budget
from collector.config import CollectorConfig
from collector.storage.models import DistributionCandidate, ValidationResult
from collector.url_utils import normalize_http_url


@dataclass
class ResourceCheckState:
    attempted: set[tuple[str, str]] = field(default_factory=set)
    checked: int = 0
    failures: list[ValidationResult] = field(default_factory=list)


@dataclass
class ResourceSelection:
    resources: list[DistributionCandidate] = field(default_factory=list)
    validations: list[ValidationResult] = field(default_factory=list)
    limited: bool = False
    budget_exhausted: bool = False


def retain_validated_resources(
    resources: list[DistributionCandidate],
    config: CollectorConfig,
    validate: Callable[[DistributionCandidate], ValidationResult],
    *,
    state: ResourceCheckState | None = None,
    context: str = "http",
    on_check: Callable[[DistributionCandidate, ValidationResult], None] | None = None,
) -> ResourceSelection:
    state = state if state is not None else ResourceCheckState()
    selection = ResourceSelection()
    for resource in sorted(resources, key=lambda item: item.probability, reverse=True):
        if state.checked >= config.max_distribution_attempts:
            selection.limited = True
            break
        url = normalize_http_url(resource.url)
        if url is None:
            continue
        key = (str(resource.signals.get("resource_key") or url), context)
        if key in state.attempted:
            continue
        try:
            check_collection_budget()
            state.attempted.add(key)
            state.checked += 1
            result = validate(resource)
        except CollectionBudgetExceeded:
            if not selection.resources:
                raise
            selection.budget_exhausted = selection.limited = True
            break
        if on_check is not None:
            on_check(resource, result)
        if not result.ok:
            state.failures.append(result)
            continue
        selection.resources.append(
            replace(resource, format=result.format, mime_type=result.mime_type)
        )
        selection.validations.append(result)
        if len(selection.resources) >= config.max_distributions_saved:
            selection.limited = len(resources) > len(selection.resources)
            break
    return selection
