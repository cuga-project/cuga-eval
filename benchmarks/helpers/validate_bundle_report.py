"""Validate report.md from an eval bundle."""

from __future__ import annotations

import re
from pathlib import Path

_REQUIRED_COLS = frozenset({"Tokens", "LLM Calls", "Cache Tokens", "Duration", "Steps"})


def _parse_table_header(line: str) -> list[str] | None:
    if not line.startswith("|") or "---" in line:
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if not cells or cells[0] in ("Task",):
        return cells
    return None


def _is_separator(line: str) -> bool:
    return line.startswith("|") and re.search(r"-{3,}", line) is not None


def validate_report_md(path: Path) -> list[str]:
    text = path.read_text()
    errors: list[str] = []

    in_per_task = False
    header_cols: list[str] | None = None
    required_indices: list[int] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## Per-Task"):
            in_per_task = True
            header_cols = None
            required_indices = []
            continue
        if in_per_task and line.startswith("## "):
            in_per_task = False
            continue
        if not in_per_task or not line.startswith("|"):
            continue
        if _is_separator(line):
            continue

        cols = _parse_table_header(line)
        if cols and cols[0] == "Task":
            header_cols = cols
            required_indices = [i for i, name in enumerate(header_cols) if name in _REQUIRED_COLS]
            continue

        if not header_cols or not required_indices:
            continue

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(header_cols):
            continue
        if all(not cells[i] for i in range(min(3, len(cells)))) and cells[-1] in ("", "—"):
            continue

        for idx in required_indices:
            col_name = header_cols[idx]
            val = cells[idx] if idx < len(cells) else ""
            if not val or val in ("--", "—", "-"):
                task_label = cells[0] or cells[1] or f"line {line_no}"
                errors.append(f"{path}:{line_no}: {col_name} is empty for task {task_label!r}")

    for label in ("Total Tokens", "Total LLM Calls", "Total Duration"):
        m = re.search(rf"\*\*{re.escape(label)}\*\*:\s*(.+)", text)
        if m:
            val = m.group(1).strip()
            if not val or val == "--":
                errors.append(f"{path}: summary {label} is missing")

    return errors


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if not args.report.is_file():
        print(f"report not found: {args.report}", file=sys.stderr)
        return 1
    errors = validate_report_md(args.report)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"OK: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
