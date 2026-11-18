"""Pick the AutomationBench policy-types subset (rule fixed 2026-11-03, before any run on these tasks).

Input: results/policy_features.json (policy_features.py). Pool: public tasks never used in a run or subset file,
without the chatgpt tool (it always fails in our adapter) and without missing tools. Each task gets one primary
policy type, first match in this order: no rule text in the data; versioned or conflicting rules; approval gate;
threshold; date or deadline; rules spread over 2+ apps; one rule document. 5 tasks per type, at most 2 per domain
per type, random with seed 20261104.

    .venv/bin/python -I select_policy_types.py      # writes policy_types_subset.json
    .venv/bin/python -I select_policy_types.py --seed 20261106 --exclude policy_types_subset.json \
        --exclude versioned_dev.json:dev --out policy_types_holdout.json      # a second, held-out draw
"""

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=20261104)
ap.add_argument(
    "--exclude", action="append", default=[], help="file.json (its tasks) or file.json:key (a list)"
)
ap.add_argument("--out", default="policy_types_subset.json")
ap.add_argument(
    "--total",
    type=int,
    help="fill up to this many tasks at random from the rest of the pool, at most 7 per domain",
)
cli = ap.parse_args()
SEED, PER_TYPE, PER_DOMAIN = cli.seed, 5, 2
TYPES = [
    ("control", "no rule text in the data (request and system message only)"),
    ("versioned", "versioned or conflicting rules (a later message supersedes or corrects a rule)"),
    ("approval", "approval or authorization gate"),
    ("threshold", "numeric threshold decides the action"),
    ("date", "date or deadline decides the action"),
    ("multi_source", "rules spread over 2+ apps"),
    ("one_doc", "one rule document"),
]


def ptype(r):
    if not r["rule_apps"]:
        return "control"
    for key, flag in (
        ("versioned", "versioned"),
        ("approval", "approval"),
        ("threshold", "threshold"),
        ("date", "date_rule"),
    ):
        if r[flag]:
            return key
    return "multi_source" if len(r["rule_apps"]) >= 2 else "one_doc"


rows = json.loads((HERE / "results" / "policy_features.json").read_text())
excluded = set()
for spec in cli.exclude:
    path, _, key = spec.partition(":")
    data = json.loads((HERE / path).read_text())
    items = data[key] if key else data["tasks"]
    excluded |= {t["task"] if isinstance(t, dict) else t for t in items}
pool = [
    r
    for r in rows
    if not r["used_before"] and not r["uses_chatgpt"] and not r["missing_tools"] and r["task"] not in excluded
]
rng = random.Random(SEED)  # noqa: S311 - seeded task selection, not security
picked = []
for key, _ in TYPES:
    cand = sorted((r for r in pool if ptype(r) == key), key=lambda r: r["task"])
    rng.shuffle(cand)
    per_dom = {}
    for r in cand:
        if len([p for p in picked if p["type"] == key]) == PER_TYPE:
            break
        if per_dom.get(r["domain"], 0) < PER_DOMAIN:
            per_dom[r["domain"]] = per_dom.get(r["domain"], 0) + 1
            picked.append(
                {
                    "task": r["task"],
                    "type": key,
                    "domain": r["domain"],
                    "n_tools": r["n_tools"],
                    "apps": r["apps"],
                    "n_checks": r["n_checks"],
                    "n_guards": r["n_guards"],
                    "rule_apps": r["rule_apps"],
                }
            )
if cli.total:  # a type with too few tasks left: fill from the rest of the pool
    rest = sorted((r for r in pool if r["task"] not in {p["task"] for p in picked}), key=lambda r: r["task"])
    rng.shuffle(rest)
    for r in rest:
        if len(picked) == cli.total:
            break
        if len([p for p in picked if p["domain"] == r["domain"]]) < 7:
            picked.append(
                {
                    "task": r["task"],
                    "type": ptype(r),
                    "domain": r["domain"],
                    "n_tools": r["n_tools"],
                    "apps": r["apps"],
                    "n_checks": r["n_checks"],
                    "n_guards": r["n_guards"],
                    "rule_apps": r["rule_apps"],
                }
            )
(HERE / cli.out).write_text(
    json.dumps(
        {
            "seed": SEED,
            "rule": __doc__.split("\n\n")[1],
            "excluded": cli.exclude,
            "types": dict(TYPES),
            "pool": len(pool),
            "tasks": picked,
        },
        indent=1,
    )
)
for p in picked:
    print(
        f'{p["type"]:12} {p["task"]:48} tools={p["n_tools"]:2} apps={len(p["apps"])} checks={p["n_checks"]:2} guards={p["n_guards"]:2} rules_in={",".join(p["rule_apps"]) or "-"}'
    )
print(len(picked), "tasks")
