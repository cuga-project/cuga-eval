#!/usr/bin/env python3
"""Create a reproducibility bundle from existing evaluation results.

Use when eval.sh finished successfully but bundle creation failed, or to
re-assemble a bundle with different options without re-running the eval.

Examples::

    # M3: bundle the latest result (mirrors eval.sh defaults)
    uv run python scripts/create_eval_bundle.py --benchmark m3 --latest

    # M3: bundle a specific result file
    uv run python scripts/create_eval_bundle.py --benchmark m3 \\
        --result-file benchmarks/m3/results/m3_20260529_020934.json

    # Any benchmark with explicit paths
    uv run python scripts/create_eval_bundle.py --benchmark bpo \\
        --result-file benchmarks/bpo/results/bpo_run.json \\
        --task-file benchmarks/bpo/data/bpo_test_suite_v1.json
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _latest_result_file(benchmark: str) -> Path | None:
    results_dir = PROJECT_ROOT / "benchmarks" / benchmark / "results"
    if not results_dir.is_dir():
        return None
    patterns = ["*.json"]
    if benchmark == "m3":
        patterns = ["m3_*.json", "multiturn_*.json"]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(results_dir.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _default_task_file(benchmark: str, result_file: Path) -> Path | None:
    data_dir = PROJECT_ROOT / "benchmarks" / benchmark / "data"
    if benchmark == "m3":
        if result_file.name.startswith("multiturn_"):
            candidate = data_dir / "olympics_mutliturn.json"
        else:
            candidate = data_dir / "hockey.json"
        return candidate if candidate.exists() else None
    return None


def _default_log_files(benchmark: str) -> list[Path]:
    bench_dir = PROJECT_ROOT / "benchmarks" / benchmark
    logs: list[Path] = []
    for name in ("registry_server.log",):
        path = bench_dir / name
        if path.is_file() and path.stat().st_size > 0:
            logs.append(path)
    # Same fixed paths as benchmarks/m3/eval.sh (not user-controlled).
    for fallback in (
        Path("/tmp/m3_registry.log"),  # noqa: S108
        Path("/tmp/m3_console.log"),  # noqa: S108
    ):
        if fallback.is_file() and fallback.stat().st_size > 0:
            logs.append(fallback)
    return logs


def _default_trajectory_dir(benchmark: str) -> Path | None:
    from benchmarks.helpers.bundle import find_latest_trajectory

    traj_root = PROJECT_ROOT / "benchmarks" / benchmark / "logging" / "trajectory_data"
    return find_latest_trajectory(traj_root)


def _generate_report(result_file: Path) -> Path | None:
    report_tmp = Path(tempfile.mkstemp(prefix=f"{result_file.stem}_report_", suffix=".md")[1])
    cmd = [
        sys.executable,
        "-m",
        "benchmarks.helpers.compare_report",
        "eval",
        "--result-file",
        str(result_file),
        "--output",
        str(report_tmp),
    ]
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError:
        report_tmp.unlink(missing_ok=True)
        return None
    return report_tmp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a reproducibility bundle from existing evaluation results."
    )
    parser.add_argument(
        "--benchmark",
        default="m3",
        help="Benchmark name (default: m3)",
    )
    parser.add_argument(
        "--result-file",
        action="append",
        dest="result_files",
        help="Result JSON path (repeatable). Omit with --latest to pick the newest file.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Use the most recent result file under benchmarks/<benchmark>/results/",
    )
    parser.add_argument(
        "--task-file",
        action="append",
        dest="task_files",
        help="Ground-truth task JSON (repeatable). Default: benchmark-specific guess for M3.",
    )
    parser.add_argument("--model-profile", default=None, help="Model profile label for bundle name")
    parser.add_argument(
        "--trajectory-dir",
        default=None,
        help="Trajectory folder to include (default: latest under logging/trajectory_data)",
    )
    parser.add_argument(
        "--log-file",
        action="append",
        dest="log_files",
        help="Log file to include (repeatable). Default: registry + console logs when present.",
    )
    parser.add_argument("--no-report", action="store_true", help="Skip eval report generation")
    parser.add_argument("--no-langfuse", action="store_true", help="Skip Langfuse trace download")
    parser.add_argument("--zip", action="store_true", help="Also create a zip archive")
    args = parser.parse_args()

    if args.latest and args.result_files:
        parser.error("Use either --latest or --result-file, not both")
    if not args.latest and not args.result_files:
        args.latest = True

    result_files: list[Path] = []
    if args.latest:
        latest = _latest_result_file(args.benchmark)
        if latest is None:
            print(
                f"No result files found under benchmarks/{args.benchmark}/results/",
                file=sys.stderr,
            )
            return 1
        result_files = [latest]
        print(f"Using latest result: {latest}")
    else:
        result_files = [Path(p).resolve() for p in args.result_files]

    for rf in result_files:
        if not rf.is_file():
            print(f"Result file not found: {rf}", file=sys.stderr)
            return 1

    task_files: list[Path] = []
    if args.task_files:
        task_files = [Path(p).resolve() for p in args.task_files]
    else:
        default_task = _default_task_file(args.benchmark, result_files[0])
        if default_task is None:
            print(
                "No --task-file given and no default task file found. Pass --task-file explicitly.",
                file=sys.stderr,
            )
            return 1
        task_files = [default_task]
        print(f"Using default task file: {default_task}")

    for tf in task_files:
        if not tf.is_file():
            print(f"Task file not found: {tf}", file=sys.stderr)
            return 1

    trajectory_dir = Path(args.trajectory_dir).resolve() if args.trajectory_dir else None
    if trajectory_dir is None:
        trajectory_dir = _default_trajectory_dir(args.benchmark)
        if trajectory_dir:
            print(f"Including trajectory: {trajectory_dir}")

    log_files = (
        [Path(p).resolve() for p in args.log_files] if args.log_files else _default_log_files(args.benchmark)
    )
    if log_files:
        print(f"Including logs: {', '.join(str(p) for p in log_files)}")

    report_path: Path | None = None
    if not args.no_report:
        report_path = _generate_report(result_files[0])
        if report_path:
            print(f"Generated report: {report_path}")

    bundle_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "benchmarks" / "helpers" / "bundle.py"),
        "assemble",
        "--benchmark",
        args.benchmark,
        "--result-files",
        *[str(p) for p in result_files],
        "--task-files",
        *[str(p) for p in task_files],
    ]
    if args.model_profile:
        bundle_cmd.extend(["--model-profile", args.model_profile])
    if trajectory_dir:
        bundle_cmd.extend(["--trajectory-dir", str(trajectory_dir)])
    if log_files:
        bundle_cmd.extend(["--log-files", *[str(p) for p in log_files]])
    if report_path:
        bundle_cmd.extend(["--report", str(report_path)])
    if not args.no_langfuse:
        bundle_cmd.append("--fetch-langfuse")
    if args.zip:
        bundle_cmd.append("--zip")

    print("Running:", " ".join(bundle_cmd))
    try:
        subprocess.run(bundle_cmd, cwd=PROJECT_ROOT, check=True)
    finally:
        if report_path:
            report_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
