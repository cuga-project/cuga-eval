#!/usr/bin/env python3
"""Sweep table: one row per arm, one column per task. Usage: sweep_stats.py <tag> [letters]"""

import collections
import glob
import json
import sys
from pathlib import Path

tag = sys.argv[1]
root = Path(__file__).parent / "harness" / "results"
NAMES = {
    "R": "alone",
    "K": "read-back",
    "F": "finish+lookup",
    "N": "F+notes(before,conflict)",
    "M": "F+notes(+after)",
    "L": "M+quoted values",
    "D": "L+default values",
    "S": "D+refusal review",
    "V": "F+refusal review",
    "Q": "requirements tracker",
    "Y": "F+code guards",
    "P": "package rules+F",
    "G": "package rules+gate+F",
    "E": "package rules+verifier+F",
    "X": "read-back+guards",
    "A": "F+all notes",
    "B": "advisor v2",
    "J": "F+policy lines",
    "U": "Y+value coverage",
    "Z": "Y+run ledger",
    "W": "Y+stated values",
    "O": "code stack",
    "H": "code stack+lines",
}
ALL_ARMS = "RKFNMYLDSVQPGEXABJUZWOH"  # pragma: allowlist secret
letters = next((x for x in sys.argv[2:] if not x.startswith("-")), ALL_ARMS)
rows, cost, tok, out, err = (
    {},
    collections.Counter(),
    collections.Counter(),
    collections.defaultdict(collections.Counter),
    collections.Counter(),
)
tasks = set()
for a in letters:
    dirs = sorted(glob.glob(str(root / f"{tag}_{a}_t*")))
    if not dirs:
        continue
    rows[a] = collections.defaultdict(list)
    for d in dirs:
        for f in glob.glob(d + "/task_*.json"):
            r = json.load(open(f))
            s = r.get("score") or {}
            if r.get("error") or s.get("primary") is None:
                err[a] += 1
                continue
            t = r["task"][-8:]
            tasks.add(t)
            rows[a][t].append((bool(s.get("pass")), s.get("partial") or 0.0))
            cost[a] += r.get("cost_usd") or 0
            for comp, u in (r.get("usage_by_component") or {}).items():
                if comp != "agent":
                    tok[a] += (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
        for au in glob.glob(d + "/work/*/audit.jsonl"):
            for line in open(au):
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if x.get("verdict"):
                    out[a][f"{x.get('component')}:{x.get('verdict')}"] += 1
tasks = sorted(tasks)
print(f"sweep {tag}: strict passes / runs per task")
print(
    f"{'arm':<28}"
    + "".join(f"{t[-4:]:>7}" for t in tasks)
    + f"{'total':>9}{'partial':>9}{'$':>7}{'policy tok':>12}{'err':>5}"
)
for a, by in rows.items():
    cells = [f"{sum(p for p, _ in by[t])}/{len(by[t])}" for t in tasks]
    allr = [x for t in tasks for x in by[t]]
    n = len(allr) or 1
    print(
        f"{a + ' ' + NAMES.get(a, ''):<28}"
        + "".join(f"{c:>7}" for c in cells)
        + f"{str(sum(p for p, _ in allr)) + '/' + str(len(allr)):>9}"
        f"{sum(x for _, x in allr) / n:>9.2f}{cost[a]:>7.2f}{tok[a]:>12}{err[a]:>5}"
    )
if "-v" in sys.argv:
    for a in rows:
        print(a, dict(out[a]))
