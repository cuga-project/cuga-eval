#!/usr/bin/env python3
"""Arms across trials: mean scores per (benchmark, set, arm) and paired per-task differences against arm A.

Arms are given as name=run[,run...] (one run directory per trial). AutomationBench runs are directories under
automationbench/results; ITSM runs are <run>:<arm letter> under enterpriseops_gym/results.

  python3 policy_eval/compare_arms.py --bench ab --set tune A=m_dsv4_A_t1,ds3_A_t2 B-block=ds1blk_B_t1,ds3blk_B_t1
  python3 policy_eval/compare_arms.py --bench eog --set tune A=m_dsv4_t1:A,ds4tA_t2:A B=ds4tB_t1:B
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path
from typing import Dict, List

B = Path(__file__).resolve().parent.parent


def load(bench: str, run: str) -> Dict[str, dict]:
    if bench == "ab":
        return {
            json.load(open(f))["task"]: json.load(open(f))
            for f in glob.glob(str(B / f"automationbench/results/{run}/*.json"))
        }
    name, arm = run.split(":")
    out = {}
    for f in glob.glob(str(B / f"enterpriseops_gym/results/{name}/{arm}_*.json")):
        r = json.load(open(f))
        out[r["task_id"]] = r
    return out


def score(bench: str, r: dict) -> Dict[str, float]:
    if bench == "ab":
        return {
            "pass": float(r["pass"]),
            "partial": r["partial_credit"],
            "aa": r["aa_style"],
            "guard": float(bool(r.get("guard_broken"))),
            "error": float(bool(r.get("error"))),
        }
    return {
        "pass": float(r["passed"]),
        "verifiers": r["verifiers_passed"] / max(1, r["verifiers_total"]),
        "error": float(bool(r.get("error"))),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["ab", "eog"], required=True)
    ap.add_argument("--set", default="")
    ap.add_argument("arms", nargs="+")
    a = ap.parse_args()
    arms = {spec.split("=", 1)[0]: spec.split("=", 1)[1].split(",") for spec in a.arms}
    per_task: Dict[str, Dict[str, List[Dict[str, float]]]] = {}
    for arm, runs in arms.items():
        for run in runs:
            for task, r in load(a.bench, run).items():
                per_task.setdefault(arm, {}).setdefault(task, []).append(score(a.bench, r))
    keys = ["pass", "partial", "aa", "guard"] if a.bench == "ab" else ["pass", "verifiers"]
    print(f"\n{a.bench} {a.set}: mean over tasks of the per-task mean over trials")
    print(
        f"{'arm':14} {'trials':>6} {'tasks':>5} "
        + " ".join(f"{k:>9}" for k in keys)
        + "  paired vs A (partial or verifiers)"
    )
    base = per_task.get("A", {})
    for arm, tasks in per_task.items():
        means = {k: statistics.mean(statistics.mean(x[k] for x in v) for v in tasks.values()) for k in keys}
        main_key = "partial" if a.bench == "ab" else "verifiers"
        common = [t for t in tasks if t in base]
        diffs = [
            statistics.mean(x[main_key] for x in tasks[t]) - statistics.mean(x[main_key] for x in base[t])
            for t in common
        ]
        better = sum(d > 0.05 for d in diffs)
        worse = sum(d < -0.05 for d in diffs)
        trials = max(len(v) for v in tasks.values())
        vals = " ".join(
            f"{means[k] * (100 if k != 'guard' else 1) * (1 if k != 'pass' else 1):9.1f}"
            if k not in ("pass", "guard")
            else f"{means[k] * len(tasks):9.1f}"
            for k in keys
        )
        print(
            f"{arm:14} {trials:>6} {len(tasks):>5} {vals}  "
            + (
                f"+{better} / -{worse} of {len(common)} tasks, mean diff {statistics.mean(diffs) * 100:+.1f} pts"
                if arm != "A" and diffs
                else ""
            )
        )
    print("(pass and guard: expected count over the task set; partial, aa, verifiers: %)")


if __name__ == "__main__":
    main()
