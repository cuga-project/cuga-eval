"""Tests for Azure content-filter detection (issue #60)."""

import json
from pathlib import Path

import pytest

from benchmarks.helpers.compare_report import (
    _parse_appworld_results,
    _parse_sdk_results,
    generate_eval_report,
    generate_report,
)
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


def test_is_content_filter_error_ignores_incidental_substring():
    """Locks in the substring-hazard fix: an error message that merely echoes
    the `content_filter_result` field name (with no `filtered...true` nearby),
    or the generic "content management policy" phrase out of context, must
    not be misclassified as a content-filter failure."""
    assert not is_content_filter_error("schema field 'content_filter_result' missing")
    assert not is_content_filter_error("content management policy service unavailable")


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


def test_eval_report_plaintext_marks_column_align(tmp_path: Path):
    """A content-filter row (mark '✗c') must column-align with a plain
    failure row (mark '✗ ') in the fixed-width plain-text Per-Task table --
    otherwise every column after the mark silently shifts by a character."""
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

    report = generate_eval_report(str(result_file), markdown=False)
    lines = {
        line.split()[0]: line for line in report.splitlines() if "2e9b91e_1" in line or "real_fail" in line
    }
    cf_line = lines["2e9b91e_1"]
    plain_line = lines["real_fail"]

    assert "✗c" in cf_line
    assert len(cf_line) == len(plain_line)
    # The cost column ("$0.0000") must start at the same character offset in
    # both rows -- if the mark cell widths ever diverge again, this shifts.
    assert cf_line.find("$0.0000") == plain_line.find("$0.0000")


def test_generate_report_multirun_mixed_failure_reasons(tmp_path: Path):
    """Two runs of the same task, one aborted by content filter and one by a
    plain agent failure. The Per-Task Details row for that task must render
    a distinct mark per run rather than collapsing to a single reason."""

    def _run(name: str, failure_reason) -> str:
        payload = {
            "metrics": {"total_tasks": 1, "passed": 0, "failed": 1, "pass_rate": 0.0},
            "results": [
                {
                    "task_name": "shared_task",
                    "success": False,
                    **({"failure_reason": failure_reason} if failure_reason else {}),
                    "total_tokens": 10,
                    "total_llm_calls": 1,
                    "full_execution_time": 1.0,
                }
            ],
        }
        p = tmp_path / name
        p.write_text(json.dumps(payload))
        return str(p)

    run_cf = _run("cf.json", FAILURE_REASON_CONTENT_FILTER)
    run_plain = _run("plain.json", None)

    report = generate_report({"gpt-oss:cuga": [run_cf, run_plain]})

    task_lines = [line for line in report.splitlines() if "shared_task" in line]
    assert len(task_lines) == 1
    # First run's cell is the content-filter mark, second run's is a plain fail.
    assert "✗c" in task_lines[0]
    assert "✗ " in task_lines[0]


def test_failure_reason_survives_sdk_and_appworld_parser_roundtrip():
    """`failure_reason` must not get dropped by either result-shape parser --
    downstream reporting depends on it surviving to the per-task dict."""
    sdk_data = {
        "metrics": {"total_tasks": 1, "passed": 0},
        "results": [
            {
                "task_name": "t1",
                "success": False,
                "failure_reason": FAILURE_REASON_CONTENT_FILTER,
            }
        ],
    }
    parsed_sdk = _parse_sdk_results(sdk_data)
    assert parsed_sdk["tasks"]["t1"]["failure_reason"] == FAILURE_REASON_CONTENT_FILTER

    appworld_data = {
        "task_results": {
            "t2": {
                "success": False,
                "failure_reason": FAILURE_REASON_CONTENT_FILTER,
            }
        },
        "tasks_total": 1,
        "tasks_completed": 0,
    }
    parsed_appworld = _parse_appworld_results(appworld_data)
    assert parsed_appworld["tasks"]["t2"]["failure_reason"] == FAILURE_REASON_CONTENT_FILTER


def test_failure_reason_from_exceptions_handles_empty_and_malformed_input():
    assert failure_reason_from_exceptions([]) is None
    assert failure_reason_from_exceptions([{"type": None, "message": None}]) is None
    assert failure_reason_from_exceptions([{"other": "field"}]) is None
