"""Compatibility imports for the collector's public collection entry points.

The implementation lives in :mod:`collector.collection.service`. New internal
callers import that module directly; existing public imports remain supported.
"""

from collector.collection.service import (
    FetchHTMLFunction as FetchHTMLFunction,
)
from collector.collection.service import (
    ValidateDistributionFunction as ValidateDistributionFunction,
)
from collector.collection.service import (
    analyze_html_page as analyze_html_page,
)
from collector.collection.service import (
    analyze_structured_page as analyze_structured_page,
)
from collector.collection.service import (
    collect_repository_candidate_with_report as collect_repository_candidate_with_report,
)
