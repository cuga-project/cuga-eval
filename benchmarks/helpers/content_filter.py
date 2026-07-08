"""Detect Azure OpenAI content-filter failures in AppWorld eval runs."""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional

FAILURE_REASON_CONTENT_FILTER = "content_filter"

# Exception class names that unambiguously indicate a content-filter rejection.
# Checked *before* any text heuristics: the class name comes straight from
# litellm/openai's exception hierarchy, so (unlike a substring scan over
# str(exc)) it can't collide with unrelated error text.
_CONTENT_FILTER_EXCEPTION_CLASSES = frozenset({"ContentPolicyViolationError"})

# Text markers used only as a fallback when no exception class name matched.
# Deliberately excludes a bare "content_filter" marker: that string is
# identical to FAILURE_REASON_CONTENT_FILTER itself, so any error message that
# merely echoes a JSON field name (e.g. "schema field 'content_filter_result'
# missing", or a log line that happens to dump a *successful* response body
# containing content_filter_result) would circularly misclassify as a
# content-filter failure. The JSON-shape case is instead matched by the
# stricter _CONTENT_FILTER_RESULT_RE regex below, which requires
# "filtered ... true" nearby, not just the bare field name.
_CONTENT_FILTER_MARKERS = (
    "responsibleaipolicyviolation",
    "content management policy",
    "content filtering policies",
)

# Label used for log messages when the JSON-shape regex marker fires.
_CONTENT_FILTER_RESULT_MARKER = "content_filter_result:filtered=true"

# Markers (including the regex marker) whose detection relies on Azure's
# current error wording/response shape rather than a stable exception class
# name. Azure has reworded these strings at least twice in the last 18
# months, so a match here is a weaker signal than the exception-class check
# and worth flagging in logs for manual verification if it ever misfires.
_FRAGILE_MARKERS = frozenset(_CONTENT_FILTER_MARKERS) | {_CONTENT_FILTER_RESULT_MARKER}

# Azure's content_filter_result payload shape, e.g.:
#   content_filter_result sexual filtered True
#   "content_filter_result": {"sexual": {"filtered": true, ...}}
# Matched via regex (not a bare substring) so a message that merely mentions
# the field name -- e.g. "schema field 'content_filter_result' missing" -- does
# not false-positive the way a plain "content_filter_result" substring check
# would.
_CONTENT_FILTER_RESULT_RE = re.compile(
    r"content_filter_result.{0,80}?filtered['\"\s:]*true", re.IGNORECASE | re.DOTALL
)


def _matched_text_marker(text: str) -> Optional[str]:
    """Return which fallback text marker matched *text*, or None."""
    lowered = text.lower()
    for marker in _CONTENT_FILTER_MARKERS:
        if marker in lowered:
            return marker
    if _CONTENT_FILTER_RESULT_RE.search(text):
        return _CONTENT_FILTER_RESULT_MARKER
    return None


def is_content_filter_error(text: str) -> bool:
    """Return True when *text* looks like an Azure content-filter rejection.

    Text-only entry point for callers that only have a message string rather
    than the exception object. Prefer `classify_exception` when the exception
    is available: the class-name check is the more stable signal (see
    `_CONTENT_FILTER_EXCEPTION_CLASSES`).
    """
    if not text:
        return False
    return _matched_text_marker(text) is not None


def classify_failure_reason(
    error_text: str,
    *,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
    """Map an error message to a stable failure-reason label, if known.

    Text-only fallback path. When *logger* is given and the match came from a
    fragile (Azure-wording-dependent) marker, emit a debug log so a future
    Azure rewording surfaces during triage instead of silently degrading.
    """
    if not error_text:
        return None
    marker = _matched_text_marker(error_text)
    if marker is None:
        return None
    if logger is not None and marker in _FRAGILE_MARKERS:
        logger.debug(f"content-filter matched via fragile marker {marker!r} — verify Azure hasn't reworded")
    return FAILURE_REASON_CONTENT_FILTER


def classify_exception(
    exc: BaseException,
    *,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
    """Classify an exception as a content-filter failure, if it is one.

    Checks the exception's class name first -- the most stable signal, since
    it comes straight from litellm/openai's exception hierarchy and can't
    collide with unrelated error text -- before falling back to a text scan
    over str(exc).
    """
    if type(exc).__name__ in _CONTENT_FILTER_EXCEPTION_CLASSES:
        return FAILURE_REASON_CONTENT_FILTER
    return classify_failure_reason(str(exc), logger=logger)


def annotate_content_filter_failure(
    result: dict[str, Any],
    error_text: str,
    *,
    exc: Optional[BaseException] = None,
    logger: Optional[logging.Logger] = None,
    task_id: Optional[str] = None,
) -> bool:
    """Tag *result* with ``failure_reason`` when the failure is a content filter.

    Pass *exc* (the original exception object) when available so the
    class-name check runs first; otherwise classification falls back to a
    text scan of *error_text*. Returns True when the failure was classified
    as a content filter.
    """
    if exc is not None:
        reason = classify_exception(exc, logger=logger)
    else:
        reason = classify_failure_reason(error_text, logger=logger)
    if reason is None:
        return False
    result["failure_reason"] = reason
    if logger is not None:
        label = f"task {task_id}" if task_id else "task"
        logger.warning(
            f"{label} aborted by Azure's content filter — scored 0.0; prompt vs. completion not "
            f"distinguishable from the captured error text; see report.md failure_reason={reason}"
        )
    return True


def log_content_filter_failure(
    logger: logging.Logger,
    error_text: str,
    *,
    exc: Optional[BaseException] = None,
    task_id: Optional[str] = None,
) -> bool:
    """Emit a dedicated log line when the failure is a content-filter rejection."""
    return annotate_content_filter_failure({}, error_text, exc=exc, logger=logger, task_id=task_id)


def failure_reason_from_exceptions(exceptions: list[Mapping[str, Any]]) -> Optional[str]:
    """Derive a failure reason from stored exception records.

    Class-name matches take priority over text-substring matches across the
    *whole* list: an early exception whose message merely contains an
    ambiguous text marker must not shadow a later exception whose recorded
    ``type`` is an unambiguous content-filter exception class name (this is
    the field ``TaskResult.add_exception`` populates with
    ``type(exception).__name__``). Only when no exception matches by class
    name do we fall back to a text scan, in list order.
    """
    for exc in exceptions:
        type_field = exc.get("type")
        if isinstance(type_field, str) and type_field in _CONTENT_FILTER_EXCEPTION_CLASSES:
            return FAILURE_REASON_CONTENT_FILTER
    for exc in exceptions:
        for field in ("message", "type"):
            text = exc.get(field)
            if isinstance(text, str):
                reason = classify_failure_reason(text)
                if reason:
                    return reason
    return None
