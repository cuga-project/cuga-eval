"""cap1 recovery pass — the VAKRA campaign's protocol for empty answers.

The official cap1 run (vakra-main ``cuga_runs/fc_canon_proto_test.sh``) generated every item at
an LLM timeout of 150 s and a per-item timeout of 220 s, then re-ran the items that came back
empty (``cap1_proto_recover.sh``): two passes, both at an LLM timeout of 300 s, a per-item
timeout of 400 s and a universe-switch timeout of 200 s, in batches of 4 with a fresh container
per batch. That took empties from 12.8% to 3.5%. This replays that protocol on the results of
``eval_m3_task_1_enterprise_style.py``: recovered non-empty answers replace the empty ones, and
the submission-format files are rewritten from the merged results.

usage (M3_DATA_DIR as for the main run):
  uv run --frozen python -m benchmarks.m3.cap1_recover --results <main-run results .json> \\
      --output <dir> [--container capability_1_bi_apis] [--adapter-preset cap1] [--demo-data ...]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PASSES = 2
BATCH = 4
AGENT_TIMEOUT = 400  # adapter per-item cap (M3_ADAPTER_AGENT_TIMEOUT)
LLM_TIMEOUT = 300  # M3_ADAPTER_LLM_HTTP_TIMEOUT
SWITCH_TIMEOUT = 200  # UNIVERSE_SWITCH_TIMEOUT_SECONDS
RUNNER = Path(__file__).resolve().parent / "eval_m3_task_1_enterprise_style.py"


def is_empty(result: Dict[str, Any]) -> bool:
    return not str(result.get("response") or "").strip()


def empties_by_domain(results: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for r in results:
        if is_empty(r):
            out.setdefault(str(r.get("domain")), []).append(str(r["uuid"]))
    return out


def batches(ids: List[str], size: int) -> List[List[str]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def merge_recovered(results: List[Dict[str, Any]], recovered: List[Dict[str, Any]]) -> int:
    """Replace empty results with recovered non-empty ones (by uuid); returns how many were filled."""
    by_uuid = {str(r.get("uuid")): r for r in recovered if not is_empty(r)}
    filled = 0
    for i, r in enumerate(results):
        new = by_uuid.get(str(r.get("uuid")))
        if new is not None and is_empty(r):
            results[i] = {**new, "recovered": True}
            filled += 1
    return filled


def restart_container(name: str) -> None:
    subprocess.run(["docker", "restart", name], capture_output=True)  # noqa: S603, S607  (docker CLI, fixed args)
    for _ in range(20):
        logs = subprocess.run(  # noqa: S603  (docker CLI, fixed args)
            ["docker", "logs", "--tail", "3", name],  # noqa: S607
            capture_output=True,
            text=True,
        )
        if "ready for exec" in (logs.stdout + logs.stderr):
            break
        time.sleep(3)
    time.sleep(2)


def run_batch(domain: str, ids: List[str], out_dir: Path, args: argparse.Namespace) -> List[Dict[str, Any]]:
    """One runner invocation over ``ids``; returns its results (empty list on failure)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "M3_ADAPTER_AGENT_TIMEOUT": str(args.agent_timeout),
        "M3_ADAPTER_LLM_HTTP_TIMEOUT": str(args.llm_timeout),
    }
    cmd = [
        sys.executable, str(RUNNER),
        "--container", args.container, "--domain", domain, "--item-ids", ",".join(ids),
        # the runner's own cap sits above the adapter's, so the adapter's 400 s governs
        "--agent-timeout", str(args.agent_timeout + 30),
        "--switch-timeout", str(args.switch_timeout),
        "--adapter-preset", args.adapter_preset, "--output", str(out_dir),
    ]  # fmt: skip
    if args.runtime:
        cmd += ["--runtime", args.runtime]
    if args.demo_data:
        cmd += ["--demo-data", args.demo_data]
    before = set(glob.glob(str(out_dir / "m3_task1_enterprise_incremental_*.json")))
    subprocess.run(cmd, env=env, check=False)  # noqa: S603  (our runner, fixed args)
    produced = sorted(set(glob.glob(str(out_dir / "m3_task1_enterprise_incremental_*.json"))) - before)
    return json.loads(Path(produced[-1]).read_text()) if produced else []


def recover(results: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    for p in range(1, args.passes + 1):
        todo = empties_by_domain(results)
        n_empty = sum(len(v) for v in todo.values())
        print(f"[recover] pass {p}: {n_empty} empty answers in {len(todo)} domains", flush=True)
        if not n_empty:
            break
        for domain, ids in todo.items():
            for b, chunk in enumerate(batches(ids, args.batch)):
                if args.restart_container:
                    restart_container(args.container)
                got = run_batch(domain, chunk, args.output / f"pass{p}" / f"{domain}_{b}", args)
                filled = merge_recovered(results, got)
                print(f"[recover] pass {p} {domain} batch {b}: {filled}/{len(chunk)} recovered", flush=True)
    left = sum(len(v) for v in empties_by_domain(results).values())
    print(f"[recover] done: {left} empty answers left of {len(results)}", flush=True)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--results", required=True, type=Path, help="the main run's results .json (list)")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--container", default="capability_1_bi_apis")
    p.add_argument("--runtime", default=None)
    p.add_argument("--adapter-preset", default="cap1")
    p.add_argument("--demo-data", default=None)
    p.add_argument("--passes", type=int, default=PASSES)
    p.add_argument("--batch", type=int, default=BATCH)
    p.add_argument("--agent-timeout", type=int, default=AGENT_TIMEOUT)
    p.add_argument("--llm-timeout", type=int, default=LLM_TIMEOUT)
    p.add_argument("--switch-timeout", type=float, default=SWITCH_TIMEOUT)
    p.add_argument("--no-restart-container", dest="restart_container", action="store_false")
    args = p.parse_args(argv)
    results = json.loads(args.results.read_text())
    merged = recover(results, args)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "m3_task1_recovered.json").write_text(json.dumps(merged, indent=2))
    from benchmarks.m3.eval_m3_task_1_enterprise_style import save_ground_truth_format  # noqa: PLC0415

    print(f"[recover] submission files: {save_ground_truth_format(merged, args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
