"""Tests for benchmarks.helpers.eval_status."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.helpers.eval_status import (
    EvalStatusWriter,
    _bind_server,
    _dashboard_is_serving,
    parse_tool_react_step,
    read_status,
)


@pytest.fixture
def status_path(tmp_path: Path) -> Path:
    return tmp_path / ".eval_status.json"


def test_writer_round_trip(status_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_STATUS_FILE", str(status_path))
    writer = EvalStatusWriter(status_path)

    writer.start_run(agent="openclaw", task_ids=["a", "b", "c"], eval_key="test_easy", model="m1")
    writer.start_task("a", 1)
    writer.finish_task({"task_name": "a", "success": True, "match_rate": 1.0})
    writer.start_task("b", 2)
    writer.finish_task({"task_name": "b", "success": False, "match_rate": 0.5})
    writer.finish_run("completed")

    data = json.loads(status_path.read_text())
    assert data["status"] == "completed"
    assert data["task_completed"] == 2
    assert data["passed"] == 1
    assert data["failed"] == 1
    assert len(data["recent"]) == 2
    assert data["recent"][0]["task_id"] == "a"
    assert data["recent"][1]["success"] is False


def test_writer_preserves_compare_on_start_run(status_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_STATUS_FILE", str(status_path))
    writer = EvalStatusWriter(status_path)
    writer.compare_start(configs=["gpt5.2:deepagents", "gpt5.2:openclaw"], overall_total=2)
    writer.compare_update(
        active_config="gpt5.2:openclaw",
        run=1,
        runs_per_config=1,
        overall_run=2,
    )

    writer.start_run(agent="openclaw", task_ids=["x"], eval_key="test_easy")
    data = json.loads(status_path.read_text())
    assert data["compare"]["active_config"] == "gpt5.2:openclaw"
    assert data["compare"]["overall_run"] == 2


def test_atomic_write_survives_rapid_updates(status_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_STATUS_FILE", str(status_path))
    writer = EvalStatusWriter(status_path)
    writer.start_run(agent="hermes", task_ids=[f"t{i}" for i in range(20)], eval_key="k")

    for i in range(1, 21):
        writer.start_task(f"t{i}", i)
        writer.finish_task({"task_name": f"t{i}", "success": i % 2 == 0, "match_rate": 0.5})

    data = json.loads(status_path.read_text())
    assert data["task_completed"] == 20
    assert len(data["recent"]) == 15


def test_parse_tool_react_step(tmp_path: Path) -> None:
    log = tmp_path / "console.log"
    log.write_text(
        "noise\n"
        "[TOOL-REACT] Step 1/12\n"
        "more\n"
        "[TOOL-REACT] Step 4/12\n"
    )
    assert parse_tool_react_step(log) == {"step": 4, "max_steps": 12}


def test_read_status_enriches_step_from_log(
    status_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVAL_STATUS_FILE", str(status_path))
    log = tmp_path / "console.log"
    log.write_text("[TOOL-REACT] Step 3/12\n")
    monkeypatch.setattr("benchmarks.helpers.eval_status.DEFAULT_CONSOLE_LOG", log)

    payload = {
        "status": "running",
        "updated_at": "2099-01-01T00:00:00Z",
        "current_task": {"id": "t1", "index": 1},
    }
    status_path.write_text(json.dumps(payload))

    data = read_status(status_path)
    assert data["current_task"]["step"] == 3
    assert data["current_task"]["max_steps"] == 12


def test_disabled_via_env(status_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_STATUS", "0")
    monkeypatch.setenv("EVAL_STATUS_FILE", str(status_path))
    writer = EvalStatusWriter(status_path)
    writer.start_run(agent="openclaw", task_ids=["a"])
    assert not status_path.exists()


def test_bind_server_uses_next_port_when_busy(tmp_path: Path) -> None:
    from http.server import SimpleHTTPRequestHandler

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path), **kwargs)

    first, port_a = _bind_server(Handler, 0)
    try:
        _, port_b = _bind_server(Handler, port_a, max_attempts=3)
        assert port_b == port_a + 1
    finally:
        first.server_close()
