#!/usr/bin/env python3
"""Select a stratified AutomationBench subset and write subset.json.

Strata are the 6 public domains. Inside each domain the task names are
shuffled with a fixed seed and the first N are kept, so a larger N always
contains the smaller subset (10 per domain is a prefix of 20 per domain).

Usage:
  .venv/bin/python select_subset.py --per-domain 10
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset

HERE = Path(__file__).resolve().parent
SEED = 20261011


def task_name(row: dict) -> str:
    info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
    return info["task_name"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-domain", type=int, default=10)
    parser.add_argument("--out", type=Path, default=HERE / "subset.json")
    args = parser.parse_args()

    tasks: dict[str, list[str]] = {}
    for domain in PUBLIC_DOMAINS:
        names = sorted(task_name(row) for row in get_domain_dataset(domain))
        random.Random(f"{SEED}-{domain}").shuffle(names)
        tasks[domain] = names[: args.per_domain]

    payload = {"seed": SEED, "per_domain": args.per_domain, "tasks": tasks}
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {sum(len(v) for v in tasks.values())} tasks to {args.out}")


if __name__ == "__main__":
    main()
