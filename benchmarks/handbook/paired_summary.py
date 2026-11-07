#!/usr/bin/env python3
"""HANDBOOK paired summary: rubric items passed per arm and trial (and the leaderboard metric: mean of per-task
rubric share), from results/<prefix>_<arm>_t<n>/*.json.   python3 handbook/paired_summary.py hbb [--arms A,L]"""

import argparse
import collections
import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("prefix")
ap.add_argument("--arms", default="A,L")
a = ap.parse_args()
for arm in a.arms.split(","):
    per = collections.defaultdict(list)
    passed = total = 0
    share = []
    for f in sorted(glob.glob(str(HERE / f"results/{a.prefix}_{arm}_t*/*.json"))):
        d = json.load(open(f))
        if "rubrics_total" not in d:
            continue
        per[d["task"][:16]].append(f'{d["rubrics_passed"]}/{d["rubrics_total"]}')
        passed += d["rubrics_passed"]
        total += d["rubrics_total"]
        share.append(d["rubrics_passed"] / max(1, d["rubrics_total"]))
    mean = 100 * sum(share) / len(share) if share else 0
    print(
        f"{arm}: {passed}/{total} items ({100 * passed / max(1, total):.1f}%), mean per-task {mean:.1f}%, runs {len(share)} | "
        + " | ".join(f"{k} {' '.join(v)}" for k, v in per.items())
    )
