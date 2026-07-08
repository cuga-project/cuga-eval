"""Tests for Azure content-filter detection (issue #60)."""

import json
from pathlib import Path

import pytest

from benchmarks.helpers.compare_report import generate_eval_report
from benchmarks.helpers.content_filter import (
    FAILURE_REASON_CONTENT_FILTER,
    annotate_content_filter_failure,
    classify_failure_reason,
    failure_reason_from_exceptions,
    is_content_filter_error,
)

pytestmark = pytest.mark.regression

_AZURE_FILTER_ERROR = (
    "Error code: 400 - litellm.ContentPolicyViolationError: The response was filtered "
    "due to the prompt triggering Azure OpenAI's content management policy. "
    "innererror code ResponsibleAIPolicyViolation content_filter_result sexual filtered True"
)


def test_is_content_filter_error_detects_azure_message():
    assert is_content_filter_error(_AZURE_FILTER_ERROR)


def test_is_content_filter_error_rejects_generic_failure():
    assert not is_content_filter_error("Connection reset by peer")
    assert not is_content_filter_error("")


def test_classify_failure_reason_returns_label():
    assert classify_failure_reason(_AZURE_FILTER_ERROR) == FAILURE_REASON_CONTENT_FILTER
    assert classify_failure_reason("timeout") is None


def test_failure_reason_from_exceptions():
    excs = [
        {
            "type": "BadRequestError",
            "message": _AZURE_FILTER_ERROR,
            "context": "run_agent_on_task_react",
        }
    ]
    assert failure_reason_from_exceptions(excs) == FAILURE_REASON_CONTENT_FILTER


def test_failure_reason_from_exceptions_falls_back_to_type_field():
    """message doesn't mention content-filter, but type does — still classified."""
    excs = [
        {
            "type": _AZURE_FILTER_ERROR,
            "message": "Connection reset by peer",
            "context": "run_agent_on_task_react",
        }
    ]
    assert failure_reason_from_exceptions(excs) == FAILURE_REASON_CONTENT_FILTER


def test_annotate_content_filter_failure_tags_result():
    result: dict = {}
    tagged = annotate_content_filter_failure(result, _AZURE_FILTER_ERROR, task_id="2e9b91e_1")
    assert tagged
    assert result["failure_reason"] == FAILURE_REASON_CONTENT_FILTER


def test_eval_report_surfaces_content_filter_failures(tmp_path: Path):
    payload = {
        "metrics": {
            "total_tasks": 2,
            "passed": 0,
            "failed": 2,
            "pass_rate": 0.0,
        },
        "results": [
            {
                "task_name": "2e9b91e_1",
                "success": False,
                "failure_reason": FAILURE_REASON_CONTENT_FILTER,
                "total_tokens": 100,
                "total_llm_calls": 3,
                "full_execution_time": 5.0,
                "steps": 2,
            },
            {
                "task_name": "real_fail",
                "success": False,
                "total_tokens": 50,
                "total_llm_calls": 1,
                "full_execution_time": 2.0,
                "steps": 1,
            },
        ],
    }
    result_file = tmp_path / "run.json"
    result_file.write_text(json.dumps(payload))

    report = generate_eval_report(str(result_file))

    assert "Content filter failures" in report
    assert "1 task(s) failed because Azure's content filter rejected the request" in report
    assert "content_filter" in report
    assert "2e9b91e_1" in report
