"""Pick the AutomationBench policy pilot before any intake code sees the tasks.

Rule (fixed 2026-10-31): public tasks whose initial sheets or emails contain the word "policy"; at most one per
domain; 5 domains and 1 task each chosen at random with seed 20261031. Only task names and domains are read here.

    benchmarks/automationbench/.venv/bin/python -I benchmarks/automationbench/select_policy_pilot.py
"""

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
SEED = 20261031


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


from automationbench.domains import PUBLIC_DOMAINS, get_domain_dataset  # noqa: E402

by_domain = {}
for dom in PUBLIC_DOMAINS:
    for row in get_domain_dataset(dom):
        info = row["info"] if isinstance(row["info"], dict) else json.loads(row["info"])
        state = info.get("initial_state", {})
        if any(re.search(r"\bpolic(y|ies)\b", s, re.I) for s in strings(state)):
            by_domain.setdefault(dom, []).append(info["task_name"])
rng = random.Random(SEED)
domains = sorted(rng.sample(sorted(by_domain), 5))
picked = [
    {"task": rng.choice(sorted(by_domain[d])), "domain": d, "policy_tasks_in_domain": len(by_domain[d])}
    for d in domains
]
(HERE / "policy_pilot.json").write_text(
    json.dumps({"seed": SEED, "rule": __doc__.split("\n\n")[1], "tasks": picked}, indent=2)
)
for p in picked:
    print(p)
