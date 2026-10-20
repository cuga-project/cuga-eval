"""Submission packaging: VAKRA's record schema, completeness against the input, recovered answers' metadata."""

import json

import pytest

from benchmarks.m3.parity import package_submission as pkg

pytestmark = pytest.mark.sanity


def test_error_category_never_passes_raw_provider_text():
    raw = "Error code: 429 - litellm.RateLimitError: see https://proxy.internal.example/v1 for limits"
    assert pkg.error_category(raw) == "RateLimitError: model provider rate limit"
    assert "longer than the model" in pkg.error_category(
        "Error code: 400 - The input (213121 tokens) is longer than the model's context length"
    )
    assert pkg.error_category("agent_timeout 300s exceeded") == "TimeoutError: agent timed out"
    assert pkg.error_category("Connection error.") == "APIConnectionError: model provider unreachable"
    assert pkg.error_category("KeyError 'x' at host-1.example") == "Error: agent run failed"
    assert pkg.error_category("") == "empty answer"


def _console(lines):
    return "\n".join(lines) + "\n"


def test_console_durations_time_each_task_from_its_first_log_line_to_its_end_line(tmp_path):
    log = tmp_path / "console.log"
    log.write_text(
        _console(
            [
                "[1/2] Processing sample...",
                "2026-10-20 22:52:00.000 | INFO     | x:y:1 - starting",
                "2026-10-20 22:52:30.500 | INFO     | x:y:2 - ✅ Completed: AA-1",
                "[2/2] Processing sample...",
                "2026-10-20 22:52:31.000 | INFO     | x:y:1 - starting",
                "2026-10-20 22:53:31.000 | ERROR    | x:y:3 - ❌ ERROR in multi-turn task BB-2: Error code: 429",
                "2026-10-20 22:53:31.000 | ERROR    | x:y:3 - ❌ ERROR in multi-turn task BB-2: Error code: 429",
            ]
        )
    )
    assert pkg.console_durations(log) == {"aa-1": 30.5, "bb-2": 60.0}
    assert pkg.console_durations(tmp_path / "missing.log") == {}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def _pred(uuid, answer, turn_id=1, calls=()):
    seq = {"tool_call": [dict(c) for c in calls], "tool_response": ["r"] * len(calls)}
    return {
        "uuid": uuid,
        "domain": "hockey",
        "output": [{"turn_id": turn_id, "query": "q", "answer": answer, "sequence": seq}],
    }


def _input_item(uuid, turn_id=1):
    return {
        "uuid": uuid,
        "domain": "hockey",
        "num_turns": 2,
        "dialogue": {"turns": [{"turn_id": 0, "query": "q0"}, {"turn_id": turn_id, "query": "q"}]},
    }


def test_package_arm_writes_every_input_task_in_order_with_recovered_answers(tmp_path, monkeypatch):
    manifests = tmp_path / "manifests"
    _write(manifests / "test_x.json", {"task_id": 4, "capability_dir": "capability_4_multiturn"})
    monkeypatch.setattr(pkg, "MANIFESTS", manifests)
    inputs = tmp_path / "input"
    _write(
        inputs / "hockey.json",
        [_input_item("H-1"), _input_item("H-2"), _input_item("H-3"), _input_item("H-4")],
    )

    runs = tmp_path / "runs"
    arm = runs / "test_run" / "cuga_eval_cap4"
    _write(arm / "meta.json", {"subset": "test_x", "cuga_agent": {"commit": "abc"}})
    _write(
        arm / "prediction" / "hockey.json",
        [
            _pred("H-1", "7", calls=[{"name": "get_x", "arguments": {"a": 1}}]),
            _pred("H-2", "8"),
            _pred("H-3", ""),
        ],
    )  # H-2 came from the recovery pass (merged); H-3 still failed; H-4 was never predicted
    _write(
        arm / "native_results.hockey.json",
        {
            "results": [
                {"uuid": "H-1", "error": None, "all_responses": [{"response": "7"}]},
                {"uuid": "H-2", "error": "Error code: 429 at https://proxy.example", "all_responses": []},
                {"uuid": "H-3", "error": "agent_timeout 300s exceeded", "all_responses": []},
            ]
        },
    )
    (arm / "console.log").write_text(
        _console(
            [
                "[1/3] Processing sample...",
                "2026-10-20 10:00:00.000 | INFO | a - go",
                "2026-10-20 10:00:10.000 | INFO | a - ✅ Completed: H-1",
            ]
        )
    )
    rec = runs / "test_run__recover1" / "cuga_eval_cap4"
    _write(
        rec / "native_results.hockey.json",
        {"results": [{"uuid": "H-2", "error": None, "all_responses": [{"response": "8"}]}]},
    )
    (rec / "console.log").write_text(
        _console(
            [
                "[1/1] Processing sample...",
                "2026-10-21 09:00:00.000 | INFO | a - go",
                "2026-10-21 09:00:42.000 | INFO | a - ✅ Completed: H-2",
            ]
        )
    )

    out = tmp_path / "out"
    report = pkg.package_arm(arm, inputs, out)
    records = json.loads((out / "capability_4_multiturn" / "hockey.json").read_text())
    assert [r["uuid"] for r in records] == ["H-1", "H-2", "H-3", "H-4"]  # input order, every task once
    by = {r["uuid"]: r for r in records}
    assert set(by["H-1"]) == {"uuid", "domain", "status", "error", "duration_s", "output"}
    assert by["H-1"]["output"] == [
        {
            "turn_id": 1,
            "query": "q",
            "answer": "7",
            "sequence": {"tool_call": [{"name": "get_x", "arguments": {"a": 1}}]},
        }
    ]  # tool_response dropped: the evaluator replays the calls
    assert (by["H-1"]["status"], by["H-1"]["duration_s"]) == ("success", 10.0)
    assert (by["H-2"]["status"], by["H-2"]["error"], by["H-2"]["duration_s"]) == ("success", "", 42.0)
    assert (by["H-3"]["status"], by["H-3"]["error"]) == ("error", "TimeoutError: agent timed out")
    assert (by["H-4"]["status"], by["H-4"]["error"], by["H-4"]["output"][0]["query"]) == (
        "error",
        "Error: task not run",
        "q",
    )
    assert report["tasks"] == 4 and report["answered"] == 2 and report["missing"] == 1
    assert report["recovery_runs"] == [str(rec)] and report["turn_id_mismatch"] == 0
    assert "proxy.example" not in (out / "capability_4_multiturn" / "hockey.json").read_text()


def test_package_arm_counts_a_turn_id_that_differs_from_the_input(tmp_path, monkeypatch):
    manifests = tmp_path / "manifests"
    _write(manifests / "test_x.json", {"task_id": 4, "capability_dir": "capability_4_multiturn"})
    monkeypatch.setattr(pkg, "MANIFESTS", manifests)
    _write(tmp_path / "input" / "hockey.json", [_input_item("H-1", turn_id=2)])
    arm = tmp_path / "runs" / "r" / "cuga_eval_cap4"
    _write(arm / "meta.json", {"subset": "test_x"})
    _write(arm / "prediction" / "hockey.json", [_pred("H-1", "7", turn_id=1)])
    assert pkg.package_arm(arm, tmp_path / "input", tmp_path / "out")["turn_id_mismatch"] == 1
