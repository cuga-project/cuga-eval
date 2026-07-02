"""Live eval status for AppWorld external-agent runs.

Writers update ``benchmarks/appworld/experiments/.eval_status.json`` during eval.
View with ``./scripts/eval_status.sh`` (opens auto-refreshing HTML dashboard).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

DEFAULT_CONSOLE_LOG = Path("/tmp/appworld_console.log")
RECENT_CAP = 15
STALE_SECONDS = 300
TOOL_REACT_STEP_RE = re.compile(r"\[TOOL-REACT\] Step (\d+)/(\d+)")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_status_path() -> Path:
    override = os.getenv("EVAL_STATUS_FILE")
    if override:
        return Path(override)
    return _project_root() / "benchmarks" / "appworld" / "experiments" / ".eval_status.json"


def default_serve_dir() -> Path:
    return default_status_path().parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enabled() -> bool:
    return os.getenv("EVAL_STATUS", "1").lower() not in ("0", "false", "no")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".eval_status_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def parse_tool_react_step(log_path: Optional[Path] = None) -> Optional[dict[str, int]]:
    path = log_path if log_path is not None else DEFAULT_CONSOLE_LOG
    if not path.is_file():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    matches = TOOL_REACT_STEP_RE.findall(text)
    if not matches:
        return None
    step, max_steps = matches[-1]
    return {"step": int(step), "max_steps": int(max_steps)}


def read_status(path: Optional[Path] = None, *, enrich: bool = True) -> dict[str, Any]:
    status_path = path or default_status_path()
    if not status_path.is_file():
        return {"status": "idle", "updated_at": None}

    try:
        data = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"status": "idle", "updated_at": None}

    if enrich:
        current = data.get("current_task") or {}
        if data.get("status") == "running" and not current.get("step"):
            parsed = parse_tool_react_step()
            if parsed:
                current = {**current, **parsed}
                data["current_task"] = current

        updated_at = data.get("updated_at")
        if updated_at and data.get("status") == "running":
            try:
                ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > STALE_SECONDS:
                    data["status"] = "idle"
                    data["stale"] = True
            except ValueError:
                pass

    return data


class EvalStatusWriter:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_status_path()
        self._data: dict[str, Any] = {}

    def _write(self) -> None:
        if not _enabled():
            return
        self._data["updated_at"] = _utc_now()
        _atomic_write(self.path, self._data)

    def _load_existing(self) -> None:
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text())
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def start_run(
        self,
        *,
        agent: str,
        task_ids: list[str],
        eval_key: Optional[str] = None,
        model: Optional[str] = None,
        benchmark: str = "appworld",
        max_steps: int = 12,
    ) -> None:
        if not _enabled():
            return
        compare = None
        if self.path.is_file():
            try:
                compare = json.loads(self.path.read_text()).get("compare")
            except (OSError, json.JSONDecodeError):
                compare = None

        self._data = {
            "status": "running",
            "benchmark": benchmark,
            "agent": agent,
            "model": model or os.getenv("MODEL_NAME"),
            "eval_key": eval_key,
            "task_total": len(task_ids),
            "task_completed": 0,
            "passed": 0,
            "failed": 0,
            "max_steps": max_steps,
            "started_at": _utc_now(),
            "current_task": None,
            "recent": [],
        }
        if compare:
            self._data["compare"] = compare
        self._write()

    def start_task(self, task_id: str, index: int) -> None:
        if not _enabled() or not self._data:
            return
        self._data["current_task"] = {
            "id": task_id,
            "index": index,
            "max_steps": self._data.get("max_steps", 12),
        }
        self._write()

    def finish_task(self, result: dict[str, Any]) -> None:
        if not _enabled() or not self._data:
            return
        success = bool(result.get("success"))
        self._data["task_completed"] = int(self._data.get("task_completed", 0)) + 1
        if success:
            self._data["passed"] = int(self._data.get("passed", 0)) + 1
        else:
            self._data["failed"] = int(self._data.get("failed", 0)) + 1

        recent = list(self._data.get("recent") or [])
        recent.append(
            {
                "task_id": result.get("task_name") or result.get("task_id"),
                "success": success,
                "match_rate": result.get("match_rate"),
            }
        )
        self._data["recent"] = recent[-RECENT_CAP:]
        self._data["current_task"] = None
        self._write()

    def finish_run(self, status: str = "completed") -> None:
        if not _enabled() or not self._data:
            return
        self._data["status"] = status
        self._data["current_task"] = None
        self._write()

    def compare_start(self, *, configs: list[str], overall_total: int) -> None:
        if not _enabled():
            return
        self._load_existing()
        self._data["compare"] = {
            "configs": configs,
            "overall_total": overall_total,
            "active_config": None,
            "run": 0,
            "runs_per_config": 0,
            "overall_run": 0,
        }
        self._write()

    def compare_update(
        self,
        *,
        active_config: str,
        run: int,
        runs_per_config: int,
        overall_run: int,
    ) -> None:
        if not _enabled():
            return
        self._load_existing()
        compare = dict(self._data.get("compare") or {})
        compare.update(
            {
                "active_config": active_config,
                "run": run,
                "runs_per_config": runs_per_config,
                "overall_run": overall_run,
            }
        )
        self._data["compare"] = compare
        self._write()


def _format_duration(started_at: Optional[str]) -> str:
    if not started_at:
        return "—"
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - start
        total = int(delta.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"
    except ValueError:
        return "—"


def print_status(data: dict[str, Any]) -> None:
    status = data.get("status", "idle")
    print(f"Status:     {status}")
    if status == "idle":
        path = default_status_path()
        print(f"Status file: {path}")
        if not path.is_file():
            print("No active or recent run. Start an eval, then re-run this command.")
        return

    agent = data.get("agent", "—")
    model = data.get("model") or "—"
    eval_key = data.get("eval_key") or "—"
    completed = data.get("task_completed", 0)
    total = data.get("task_total", 0)
    passed = data.get("passed", 0)
    failed = data.get("failed", 0)

    print(f"Agent:      {agent}")
    print(f"Model:      {model}")
    print(f"Eval key:   {eval_key}")
    print(f"Progress:   {completed}/{total} tasks")
    print(f"Passed:     {passed}  Failed: {failed}")
    print(f"Elapsed:    {_format_duration(data.get('started_at'))}")

    compare = data.get("compare")
    if compare:
        print(
            f"Compare:    {compare.get('active_config')} "
            f"(run {compare.get('run')}/{compare.get('runs_per_config')}, "
            f"overall {compare.get('overall_run')}/{compare.get('overall_total')})"
        )

    current = data.get("current_task")
    if current:
        step = current.get("step")
        max_steps = current.get("max_steps", 12)
        step_str = f", step {step}/{max_steps}" if step else ""
        print(f"Current:    [{current.get('index')}/{total}] {current.get('id')}{step_str}")

    print(f"Updated:    {data.get('updated_at', '—')}")


def _open_browser(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    else:
        webbrowser.open(url)


def _dashboard_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/status.html"


def _dashboard_is_serving(port: int) -> bool:
    try:
        with urllib.request.urlopen(_dashboard_url(port), timeout=1) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _bind_server(
    handler: type[SimpleHTTPRequestHandler],
    port: int,
    *,
    max_attempts: int = 10,
) -> tuple[ThreadingHTTPServer, int]:
    last_err: Optional[OSError] = None
    for attempt in range(max_attempts):
        candidate = port + attempt
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            return server, int(server.server_address[1])
        except OSError as exc:
            if exc.errno not in (48, 98):  # macOS / Linux "address already in use"
                raise
            last_err = exc
    raise OSError(
        f"No free port in range {port}-{port + max_attempts - 1}: {last_err}"
    ) from last_err


def serve_dashboard(*, port: int = 8765, no_open: bool = False) -> None:
    serve_dir = default_serve_dir()
    serve_dir.mkdir(parents=True, exist_ok=True)
    status_name = default_status_path().name

    if _dashboard_is_serving(port):
        url = _dashboard_url(port)
        print(f"Dashboard already running at {url}")
        print(f"Status JSON: {default_status_path()}")
        if not no_open:
            _open_browser(url)
        return

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send_head(self):
            clean = self.path.split("?", 1)[0]
            if clean == f"/{status_name}":
                path = serve_dir / status_name
                if path.is_file():
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    st = path.stat()
                    self.send_header("Content-Length", str(st.st_size))
                    self.end_headers()
                    return open(path, "rb")
            return super().send_head()

    server, bound_port = _bind_server(Handler, port)
    url = _dashboard_url(bound_port)
    print(f"Serving dashboard from {serve_dir}")
    print(f"Dashboard:  {url}")
    if bound_port != port:
        print(f"Note: port {port} was busy; using {bound_port} instead.")
    print(f"Status JSON: {default_status_path()}")
    print("Press Ctrl+C to stop.")

    if not no_open:
        threading.Timer(0.3, lambda: _open_browser(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def _cmd_compare_start(args: argparse.Namespace) -> None:
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    EvalStatusWriter().compare_start(configs=configs, overall_total=args.overall_total)


def _cmd_compare_update(args: argparse.Namespace) -> None:
    EvalStatusWriter().compare_update(
        active_config=args.active_config,
        run=args.run,
        runs_per_config=args.runs_per_config,
        overall_run=args.overall_run,
    )


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="AppWorld eval status dashboard")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Start dashboard HTTP server and open browser")
    serve_p.add_argument("--port", type=int, default=8765)
    serve_p.add_argument("--no-open", action="store_true", help="Do not open browser")

    sub.add_parser("print", help="Print one-shot status summary")
    sub.add_parser("path", help="Print status file path")

    cmp_start = sub.add_parser("compare-start", help="Initialize compare-run metadata")
    cmp_start.add_argument("--configs", required=True, help="Comma-separated config labels")
    cmp_start.add_argument("--overall-total", type=int, required=True)

    cmp_up = sub.add_parser("compare-update", help="Update active compare config")
    cmp_up.add_argument("--active-config", required=True)
    cmp_up.add_argument("--run", type=int, required=True)
    cmp_up.add_argument("--runs-per-config", type=int, required=True)
    cmp_up.add_argument("--overall-run", type=int, required=True)

    args = parser.parse_args(argv)
    cmd = args.command or "serve"

    if cmd == "serve":
        serve_dashboard(port=args.port, no_open=args.no_open)
    elif cmd == "print":
        print_status(read_status())
    elif cmd == "path":
        print(default_status_path())
    elif cmd == "compare-start":
        _cmd_compare_start(args)
    elif cmd == "compare-update":
        _cmd_compare_update(args)
    else:
        parser.error(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
