#!/usr/bin/env python3
"""Paired τ² summary for launch_paired.py runs: pass count per arm, per-task wins/losses, termination reasons, costs
(agent tokens from usage.jsonl when present). python3 policy_eval/tau2/paired_summary.py <tag> [--arms A,T]"""

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_pilot_costs as ppc  # noqa: E402

T2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"
PRICE = {
    "agent": (1.74, 3.48),
    "sim": (2.00, 8.00),
    "tracker": (0.15, 0.60),
}  # DeepSeek-V4-Pro, gpt-4.1, gpt-oss-120b


def load(tag, arm):
    rows, usage = {}, []
    for d in sorted(T2.glob(f"logging_{tag}_{arm}_s*")):
        for f in (d / "results").glob("*.json"):
            j = json.load(open(f))
            for r in (j.get("results") if isinstance(j, dict) else j) or []:
                rows[r["task_id"]] = r
        u = d / "usage.jsonl"
        if u.exists():
            usage += [json.loads(line) for line in u.read_text().splitlines() if line.strip()]
    return rows, usage


ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--arms", default="A,T")
ap.add_argument(
    "--record", action="store_true", help="add the agent+tracker cost (+ simulator estimate) to the ledger"
)
a = ap.parse_args()
arms = a.arms.split(",")
data = {arm: load(a.tag, arm) for arm in arms}
ok = lambda r: float(r.get("reward") or 0) >= 1  # noqa: E731
common = sorted(set.intersection(*[set(d[0]) for d in data.values()]))
for arm in arms:
    rows, usage = data[arm]
    term = collections.Counter(r["termination_reason"] for r in rows.values())
    ain = sum(u.get("agent_in", 0) for u in usage)
    aout = sum(u.get("agent_out", 0) for u in usage)
    tin = sum(u.get("tracker_in", 0) for u in usage)
    tout = sum(u.get("tracker_out", 0) for u in usage)
    cost = (
        ain * PRICE["agent"][0]
        + aout * PRICE["agent"][1]
        + tin * PRICE["tracker"][0]
        + tout * PRICE["tracker"][1]
    ) / 1e6
    print(
        f"{arm}: {sum(ok(rows[t]) for t in common)}/{len(common)} on common tasks ({len(rows)} done) | {dict(term)} | "
        f"agent {ain / 1e6:.2f}M in, tracker {tin / 1e6:.2f}M in, notes {sum(u.get('notes', 0) for u in usage)} | ${cost:.2f} (no simulator)"
    )
    if a.record and rows:
        with ppc.LEDGER.open("a") as fh:
            from estimate_cost import (
                estimate,  # simulator cost from the scored conversations (gpt-4.1 $2/$8 per 1M)
            )

            sim = 0.0
            for d in sorted(T2.glob(f"logging_{a.tag}_{arm}_s*")):
                _, _, _, ui, uo = estimate(d, 0)
                sim += (ui * 2.0 + uo * 8.0) / 1e6
            fh.write(
                json.dumps(
                    {
                        "ts": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
                        "kind": "tau2_paired",
                        "name": f"tau2/{a.tag}_{arm}",
                        "agent_in": ain,
                        "agent_out": aout,
                        "policy_in": tin,
                        "policy_out": tout,
                        "policy_calls": 0,
                        "cost_usd": round(cost + sim, 4),
                    }
                )
                + "\n"
            )
if len(arms) == 2:
    x, y = arms
    win = [t for t in common if ok(data[y][0][t]) and not ok(data[x][0][t])]
    loss = [t for t in common if ok(data[x][0][t]) and not ok(data[y][0][t])]
    print(f"{y} vs {x}: +{len(win)} / -{len(loss)}")
    for t in win:
        print("  WIN ", t[:110])
    for t in loss:
        print("  LOSS", t[:110])
if a.record:
    print(f"ledger now ${ppc.spent():.2f}")
