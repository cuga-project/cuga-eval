"""Unit tests for benchmarks.helpers.run_state (Slice C)."""

from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmarks.helpers.incremental_results import write_task_result
from benchmarks.helpers.run_state import (
    STATUS_COMPLETED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    effective_status,
    format_status_line,
    is_process_alive,
    mark_finished,
    mark_running,
    read_run_state,
    run_state_path,
    stop_run,
    write_run_state,
)


@pytest.mark.sanity
def test_write_and_read_run_state(tmp_path: Path):
    write_run_state(tmp_path, status=STATUS_RUNNING, pid=1234)
    state = read_run_state(tmp_path)
    assert state is not None
    assert state["status"] == STATUS_RUNNING
    assert state["pid"] == 1234
    assert run_state_path(tmp_path).is_file()


@pytest.mark.sanity
def test_is_process_alive_current_process():
    assert is_process_alive(os.getpid(), None) is True


@pytest.mark.sanity
def test_is_process_alive_dead_pid():
    assert is_process_alive(999999999, None) is False


@pytest.mark.sanity
def test_is_process_alive_wrong_host():
    assert is_process_alive(os.getpid(), "other-host.example") is False


@pytest.mark.sanity
def test_effective_status_stale_running(tmp_path: Path):
    mark_running(tmp_path, pid=999999999)
    state = read_run_state(tmp_path)
    assert effective_status(tmp_path, state) == STATUS_STOPPED


@pytest.mark.sanity
def test_format_status_includes_task_counts(tmp_path: Path):
    write_task_result(tmp_path, "task-a", {"task_name": "task-a", "error": None, "success": True})
    write_task_result(tmp_path, "task-b", {"task_name": "task-b", "error": "boom", "success": False})
    mark_running(tmp_path, pid=os.getpid(), total_tasks=5)
    text = format_status_line(tmp_path, read_run_state(tmp_path))
    assert "tasks:" in text
    assert "1/5 completed" in text


@pytest.mark.sanity
def test_mark_finished_success(tmp_path: Path):
    mark_running(tmp_path, pid=os.getpid())
    mark_finished(tmp_path, exit_code=0)
    state = read_run_state(tmp_path)
    assert state is not None
    assert state["status"] == STATUS_COMPLETED


@pytest.mark.sanity
def test_mark_finished_sigterm_is_stopped(tmp_path: Path):
    mark_running(tmp_path, pid=os.getpid())
    mark_finished(tmp_path, exit_code=143)
    state = read_run_state(tmp_path)
    assert state is not None
    assert state["status"] == STATUS_STOPPED


@pytest.mark.sanity
def test_stop_run_not_alive(tmp_path: Path, capsys):
    mark_running(tmp_path, pid=999999999)
    rc = stop_run(tmp_path)
    assert rc == 0
    assert "not alive" in capsys.readouterr().out


@pytest.mark.sanity
def test_stop_run_sends_sigterm(tmp_path: Path):
    mark_running(tmp_path, pid=os.getpid())
    with patch("benchmarks.helpers.run_state.os.kill") as mock_kill:
        mock_kill.side_effect = [None, ProcessLookupError()]
        with patch("benchmarks.helpers.run_state.is_process_alive", side_effect=[True, False]):
            rc = stop_run(tmp_path, timeout=1.0)
    assert rc == 0
    mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)
