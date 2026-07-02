"""Background run lifecycle state (Slice C).

``run_state.json`` lives at the experiment workspace bundle root and is the
single source of truth for ``--status`` / ``--stop`` regardless of whether the
run was started in the foreground or via ``--background``.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from benchmarks.helpers.incremental_results import (
    load_completed_task_ids,
    partial_dir,
)

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"

RUN_STATE_FILENAME = "run_state.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hostname() -> str:
    return socket.gethostname()


def run_state_path(bundle_dir: Path) -> Path:
    return Path(bundle_dir) / RUN_STATE_FILENAME


def read_run_state(bundle_dir: Path) -> Optional[Dict[str, Any]]:
    path = run_state_path(bundle_dir)
    if not path.is_file():
        return None
    import json

    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_run_state(bundle_dir: Path, **fields: Any) -> Path:
    """Merge ``fields`` into ``run_state.json`` atomically."""
    from benchmarks.helpers.incremental_results import atomic_write_json

    bundle_dir = Path(bundle_dir)
    existing = read_run_state(bundle_dir) or {}
    existing.update(fields)
    existing.setdefault("updated_at", _utc_now())
    if "updated_at" not in fields:
        existing["updated_at"] = _utc_now()
    return atomic_write_json(run_state_path(bundle_dir), existing)


def is_process_alive(pid: Optional[int], host: Optional[str]) -> bool:
    """Return True when ``pid`` appears alive on ``host`` (this host only)."""
    if pid is None:
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    if host and host != hostname():
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — treat as alive.
        return True
    except OSError:
        return False
    return True


def count_partial_files(bundle_dir: Path) -> int:
    pdir = partial_dir(bundle_dir)
    if not pdir.is_dir():
        return 0
    return sum(1 for _ in pdir.glob("*.json"))


def effective_status(bundle_dir: Path, state: Optional[Dict[str, Any]]) -> str:
    if state is None:
        return "unknown"
    recorded = state.get("status") or STATUS_RUNNING
    if recorded == STATUS_RUNNING and not is_process_alive(state.get("pid"), state.get("host")):
        return STATUS_STOPPED
    return str(recorded)


def format_status_line(bundle_dir: Path, state: Optional[Dict[str, Any]]) -> str:
    bundle_dir = Path(bundle_dir)
    status = effective_status(bundle_dir, state)
    if state is None:
        return f"bundle: {bundle_dir}\nstatus: no run_state.json"

    completed = state.get("completed_tasks")
    if completed is None:
        completed = len(load_completed_task_ids(bundle_dir))
    total = state.get("total_tasks")
    partials = count_partial_files(bundle_dir)

    lines = [
        f"bundle: {bundle_dir}",
        f"status: {status}",
        f"pid: {state.get('pid', '—')} (host: {state.get('host', '—')})",
        f"started: {state.get('started_at', '—')}",
        f"updated: {state.get('updated_at', '—')}",
    ]
    if total is not None:
        lines.append(f"tasks: {completed}/{total} completed ({partials} partial files on disk)")
    else:
        lines.append(f"tasks: {completed} completed ({partials} partial files on disk)")
    if state.get("exit_code") is not None:
        lines.append(f"exit_code: {state['exit_code']}")
    return "\n".join(lines)


def mark_running(bundle_dir: Path, *, pid: int, total_tasks: Optional[int] = None) -> Path:
    payload: Dict[str, Any] = {
        "status": STATUS_RUNNING,
        "pid": pid,
        "host": hostname(),
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "exit_code": None,
    }
    if total_tasks is not None:
        payload["total_tasks"] = total_tasks
    return write_run_state(bundle_dir, **payload)


def mark_finished(
    bundle_dir: Path,
    *,
    exit_code: int,
    total_tasks: Optional[int] = None,
) -> Path:
    completed = len(load_completed_task_ids(bundle_dir))
    status = STATUS_COMPLETED if exit_code == 0 else STATUS_FAILED
    if exit_code in (130, 143, -15, -2):
        # SIGINT / SIGTERM — user stop
        status = STATUS_STOPPED
    payload: Dict[str, Any] = {
        "status": status,
        "exit_code": exit_code,
        "completed_tasks": completed,
        "updated_at": _utc_now(),
    }
    if total_tasks is not None:
        payload["total_tasks"] = total_tasks
    existing = read_run_state(bundle_dir)
    if existing and existing.get("pid") is not None:
        payload["pid"] = existing["pid"]
        payload["host"] = existing.get("host")
        payload.setdefault("started_at", existing.get("started_at"))
    return write_run_state(bundle_dir, **payload)


def stop_run(bundle_dir: Path, *, timeout: float = 15.0) -> int:
    """Send SIGTERM to the recorded pid, escalate to SIGKILL if needed."""
    state = read_run_state(bundle_dir)
    if state is None:
        print(f"No run_state.json under {bundle_dir}", file=sys.stderr)
        return 1

    # A run already in a terminal state must never be signaled — its pid may
    # have been reused by an unrelated process since the run finished, and
    # signaling that process (then recording the run as freshly "stopped")
    # would both kill something we don't own and corrupt a completed run's
    # recorded status.
    recorded_status = state.get("status") or STATUS_RUNNING
    if recorded_status != STATUS_RUNNING:
        print(f"Run is not running (status: {recorded_status})")
        return 0

    pid = state.get("pid")
    host = state.get("host")
    if not is_process_alive(pid, host):
        write_run_state(
            bundle_dir,
            status=STATUS_STOPPED,
            exit_code=state.get("exit_code"),
            updated_at=_utc_now(),
        )
        print(f"Run is not alive (status: {effective_status(bundle_dir, state)})")
        return 0

    pid_int = int(pid)  # type: ignore[arg-type]
    try:
        os.kill(pid_int, signal.SIGTERM)
    except ProcessLookupError:
        mark_finished(bundle_dir, exit_code=143)
        return 0
    except OSError as e:
        print(f"Failed to signal pid {pid_int}: {e}", file=sys.stderr)
        return 1

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_alive(pid_int, host):
            mark_finished(bundle_dir, exit_code=143)
            print(f"Stopped run (pid {pid_int})")
            return 0
        time.sleep(0.25)

    try:
        os.kill(pid_int, signal.SIGKILL)
    except OSError:
        pass
    # exit_code=137 (128+SIGKILL) would map to STATUS_FAILED via mark_finished's
    # generic exit-code inference — but this is a user-initiated stop that had
    # to escalate, not a task failure. Override the status explicitly.
    mark_finished(bundle_dir, exit_code=137)
    write_run_state(bundle_dir, status=STATUS_STOPPED, updated_at=_utc_now())
    print(f"Force-killed run (pid {pid_int})")
    return 0


def cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run lifecycle CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Print run status for a bundle dir")
    p_status.add_argument("--bundle-dir", required=True)

    p_stop = sub.add_parser("stop", help="Stop a background run")
    p_stop.add_argument("--bundle-dir", required=True)
    p_stop.add_argument("--timeout", type=float, default=15.0)

    p_run = sub.add_parser("mark-running", help="Record a running process")
    p_run.add_argument("--bundle-dir", required=True)
    p_run.add_argument("--pid", type=int, required=True)
    p_run.add_argument("--total-tasks", type=int, default=None)

    p_fin = sub.add_parser("mark-finished", help="Record run completion")
    p_fin.add_argument("--bundle-dir", required=True)
    p_fin.add_argument("--exit-code", type=int, required=True)
    p_fin.add_argument("--total-tasks", type=int, default=None)

    args = parser.parse_args(argv)
    bundle_dir = Path(args.bundle_dir)

    if args.command == "status":
        state = read_run_state(bundle_dir)
        print(format_status_line(bundle_dir, state))
        return 0

    if args.command == "stop":
        return stop_run(bundle_dir, timeout=args.timeout)

    if args.command == "mark-running":
        mark_running(bundle_dir, pid=args.pid, total_tasks=args.total_tasks)
        return 0

    if args.command == "mark-finished":
        mark_finished(bundle_dir, exit_code=args.exit_code, total_tasks=args.total_tasks)
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
