#!/usr/bin/env python3
"""CLI wrapper for bundle report validation."""

import argparse
import sys
from pathlib import Path

from benchmarks.helpers.validate_bundle_report import validate_report_md


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate report.md from an eval bundle (metrics must be populated)."
    )
    parser.add_argument("report", type=Path, help="Path to report.md")
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
