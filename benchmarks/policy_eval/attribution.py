#!/usr/bin/env python3
"""Was arm B's gain where the layer acted? For each B task run, mark whether the layer showed the agent anything
(remind or deny, any rule), then compare its score with the same task's mean in arm A.

  python3 policy_eval/attribution.py --a m_dsv4_A_t1,ds3_A_t2,ds4_A_t3 --b ds3rem_B_t1,ds4rem_B_t2,ds4rem_B_t3
"""

import argparse
import glob
import json
import statistics
from collections import defaultdict
from pathlib import Path

B = Path(__file__).resolve().parent.parent


def runs(names):
    out = defaultdict(list)
    for n in names:
        for f in glob.glob(str(B / f"automationbench/results/{n}/*.json")):
            r = json.load(open(f))
            out[r["task"]].append(r)
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True)
ap.add_argument("--b", required=True)
a = ap.parse_args()
A, Bx = runs(a.a.split(",")), runs(a.b.split(","))
groups = {"layer acted": [], "layer silent": []}
guard = {"layer acted": [0, 0, 0], "layer silent": [0, 0, 0]}  # [B runs, B guard breaks, A guard rate sum]
for task, rs in Bx.items():
    if task not in A:
        continue
    a_pc = statistics.mean(r["partial_credit"] for r in A[task])
    a_guard = statistics.mean(float(bool(r.get("guard_broken"))) for r in A[task])
    for r in rs:
        acted = any(g.get("outcome") in ("remind", "deny") for g in r.get("gate") or [])
        k = "layer acted" if acted else "layer silent"
        groups[k].append(r["partial_credit"] - a_pc)
        guard[k][0] += 1
        guard[k][1] += bool(r.get("guard_broken"))
        guard[k][2] += a_guard
for k, d in groups.items():
    if d:
        n, gb, ga = guard[k]
        print(
            f"{k:13} B runs {len(d):3}  partial vs A {statistics.mean(d) * 100:+5.1f} pts  "
            f"(better {sum(x > 0.05 for x in d)}, worse {sum(x < -0.05 for x in d)})  "
            f"guardrail breaks: B {gb}/{n} vs A expected {ga:.1f}"
        )
