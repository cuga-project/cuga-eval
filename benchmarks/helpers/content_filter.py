"""Detect Azure OpenAI content-filter failures in AppWorld eval runs."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

FAILURE_REASON_CONTENT_FILTER = "content_filter"

_CONTENT_FILTER_MARKERS = (
    "contentpolicyviolationerror",
    "responsibleaipolicyviolation",
    "content_filter",
    "content management policy",
    "content filtering policies",
)


def is_content_filter_error(text: str) -> bool:
    """Return True when *text* looks like an Azure content-filter rejection."""
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _CONTENT_FILTER_MARKERS)


def classify_failure_reason(error_text: str) -> Optional[str]:
    """Map an error message to a stable failure-reason label, if known."""
    if is_content_filter_error(error_text):
        return FAILURE_REASON_CONTENT_FILTER
    return None


def annotate_content_filter_failure(
    result: dict[str, Any],
    error_text: str,
    *,
    logger: Optional[logging.Logger] = None,
    task_id: Optional[str] = None,
) -> bool:
    """Tag *result* with ``failure_reason`` when *error_text* is a content filter.

    Returns True when the failure was classified as a content filter.
    """
    reason = classify_failure_reason(error_text)
    if reason is None:
        return False
    result["failure_reason"] = reason
    if logger is not None:
        label = f"task {task_id}" if task_id else "task"
        logger.warning(
            f"{label} aborted by Azure content filter (false positive likely) — "
            f"scored 0.0; see report.md failure_reason={reason}"
        )
    return True


def log_content_filter_failure(
    logger: logging.Logger,
    error_text: str,
    *,
    task_id: Optional[str] = None,
) -> bool:
    """Emit a dedicated log line when *error_text* is a content-filter rejection."""
    return annotate_content_filter_failure({}, error_text, logger=logger, task_id=task_id)


def failure_reason_from_exceptions(exceptions: list[Mapping[str, Any]]) -> Optional[str]:
    """Derive a failure reason from stored exception records."""
    for exc in exceptions:
        for field in ("message", "type"):
            text = exc.get(field)
            if isinstance(text, str):
                reason = classify_failure_reason(text)
                if reason:
                    return reason
    return None
