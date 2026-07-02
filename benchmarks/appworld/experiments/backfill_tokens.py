#!/usr/bin/env python3
"""Backfill per-task token fields in AppWorld final_report JSON from Langfuse traces."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from benchmarks.helpers.sdk_eval_helpers import fetch_langfuse_metrics_for_trace


async def backfill_report(path: Path, *, dry_run: bool = False) -> dict:
    data = json.loads(path.read_text())
    results = data.get("results") or []
    updated = 0
    skipped = 0
    failed = 0

    for result in results:
        if result.get("total_tokens"):
            skipped += 1
            continue
        trace_id = result.get("trace_id")
        if not trace_id:
            skipped += 1
            continue
        try:
            metrics = await fetch_langfuse_metrics_for_trace(trace_id)
        except Exception as exc:
            print(f"  {result.get('task_name')}: fetch failed ({exc})")
            failed += 1
            continue
        if not metrics or not getattr(metrics, "total_tokens", 0):
            failed += 1
            continue
        result["total_tokens"] = metrics.total_tokens
        result["total_llm_calls"] = metrics.total_llm_calls
        if getattr(metrics, "total_cost", None) is not None:
            result["total_cost"] = metrics.total_cost
        if getattr(metrics, "total_cache_input_tokens", 0):
            result["total_cache_input_tokens"] = metrics.total_cache_input_tokens
        updated += 1

    from benchmarks.helpers.token_usage import rollup_token_metrics

    data.setdefault("metrics", {}).update(rollup_token_metrics(results))

    out_path = path.with_name(path.stem + ".with_tokens.json")
    if not dry_run:
        out_path.write_text(json.dumps(data, indent=2, default=str))

    return {
        "source": str(path),
        "output": str(out_path),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "total_tokens": sum(r.get("total_tokens", 0) or 0 for r in results),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill token metrics from Langfuse trace IDs")
    parser.add_argument(
        "reports",
        nargs="+",
        type=Path,
        help="Paths to *_final_report.json files",
    )
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write output files")
    args = parser.parse_args()

    exit_code = 0
    for report in args.reports:
        if not report.is_file():
            print(f"Missing file: {report}")
            exit_code = 1
            continue
        print(f"Backfilling {report} ...")
        summary = await backfill_report(report, dry_run=args.dry_run)
        print(
            f"  updated={summary['updated']} skipped={summary['skipped']} "
            f"failed={summary['failed']} total_tokens={summary['total_tokens']}"
        )
        if not args.dry_run and summary["updated"]:
            print(f"  wrote {summary['output']}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
