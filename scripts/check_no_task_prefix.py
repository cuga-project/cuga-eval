#!/usr/bin/env python3
"""Smoke test: assert that no tool call in an M3 result file carries the legacy
``task_<n>_<domain>_`` registry prefix.

The registry was reconfigured (eval_m3.py + m3_data_loader.py + m3_vakra_score.py)
to use the bare domain name as the app namespace, so saved tool calls should
now start with ``<domain>_`` rather than ``task_<n>_<domain>_``. This script
walks every recorded tool call in a result file and fails if any one of them
still starts with the legacy form — that would mean the change regressed.

Usage:
    uv run python scripts/check_no_task_prefix.py <result-file.json>

    # Or, with no arg, picks the most recent benchmarks/m3/results/m3_config_*.json
    uv run python scripts/check_no_task_prefix.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LEGACY_RE = re.compile(r"^task_\d+_[a-z_]+_")


def _iter_tool_calls(obj):
    """Yield every (tool_call_dict, path-for-error-msg) pair under obj."""
    # Top-level result-file shapes vary across writers (results.json has
    # {"metrics": ..., "results": [...]} for SDK eval; the bundle CSV-paired
    # file has {uuid: {"tool_calls": [...]}} for legacy m3 runs). Cover both.
    if isinstance(obj, dict) and "results" in obj and isinstance(obj["results"], list):
        for i, r in enumerate(obj["results"]):
            yield from _walk(r, f"results[{i}]")
    elif isinstance(obj, dict):
        # Per-uuid map
        for k, v in obj.items():
            if isinstance(v, dict):
                yield from _walk(v, k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk(item, f"[{i}]")


def _walk(node, path):
    if not isinstance(node, dict):
        return
    for tc in node.get("tool_calls", []) or []:
        if isinstance(tc, dict):
            yield tc, f"{path}.tool_calls"
    for j, turn in enumerate(node.get("all_responses", []) or []):
        if isinstance(turn, dict):
            for tc in turn.get("tool_calls", []) or []:
                if isinstance(tc, dict):
                    yield tc, f"{path}.all_responses[{j}].tool_calls"


def _newest_default_result_file() -> Path | None:
    candidates = sorted(
        Path("benchmarks/m3/results").glob("m3_config_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        path = Path(argv[1])
    else:
        path = _newest_default_result_file()
        if path is None:
            print(
                "No result file passed and none found under benchmarks/m3/results/m3_config_*.json",
                file=sys.stderr,
            )
            return 2
        print(f"(no path given — using latest: {path})", file=sys.stderr)

    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    data = json.loads(path.read_text())
    offenders: list[tuple[str, str]] = []
    total = 0
    for tc, where in _iter_tool_calls(data):
        total += 1
        name = tc.get("name") or ""
        if LEGACY_RE.match(name):
            offenders.append((where, name))

    if offenders:
        print(
            f"FAIL — {len(offenders)} of {total} tool calls still carry the legacy task_<n>_<domain>_ prefix:",
            file=sys.stderr,
        )
        for where, name in offenders[:20]:
            print(f"  {where}: {name}", file=sys.stderr)
        if len(offenders) > 20:
            print(f"  … and {len(offenders) - 20} more", file=sys.stderr)
        return 1

    print(f"OK — {total} tool call(s) checked, none start with the legacy task_<n>_<domain>_ prefix.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
