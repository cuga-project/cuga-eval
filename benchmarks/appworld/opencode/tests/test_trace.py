"""Tests for shaping bridge tool-calls into the OpenCode Langfuse trace output.

The harness trace must surface the *generated code* per tool call (not just the tool name), so
that it is visible in Langfuse. These tests pin that shape with a pure data transform — no
AppWorld servers, Langfuse, or the opencode binary required.
"""

from __future__ import annotations

import sys
from pathlib import Path

APPWORLD_DIR = Path(__file__).resolve().parents[2]
if str(APPWORLD_DIR) not in sys.path:
    sys.path.insert(0, str(APPWORLD_DIR))

from opencode.trace import summarize_tool_calls_for_trace


def test_includes_generated_code_and_truncates_output():
    calls = [{"name": "execute_python", "args": {"code": "apis.spotify.show()"}, "output": "R" * 5000}]
    res = summarize_tool_calls_for_trace(calls, output_limit=2000)
    assert len(res) == 1
    assert res[0]["name"] == "execute_python"
    assert res[0]["code"] == "apis.spotify.show()"  # the generated code is present
    assert len(res[0]["output"]) == 2000  # long output is truncated


def test_apis_mode_keeps_args_and_null_code():
    calls = [
        {
            "name": "spotify__login",
            "args": {"app": "spotify", "api": "login", "arguments": {"x": 1}},
            "output": "ok",
        }
    ]
    res = summarize_tool_calls_for_trace(calls)
    assert res[0]["code"] is None  # apis mode has no `code`
    assert res[0]["args"]["api"] == "login"  # full args retained
    assert res[0]["output"] == "ok"


def test_handles_missing_fields():
    res = summarize_tool_calls_for_trace([{"name": "execute_python"}])
    assert res[0]["code"] is None
    assert res[0]["args"] == {}
    assert res[0]["output"] == ""
