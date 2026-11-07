"""Pick the EnterpriseOps-Gym ITSM pilot tasks before any agent or policy code sees them.

Rule (fixed 2026-10-31): drop the tasks with known broken verifiers (upstream issues #21, #22),
then take one task at random from each of the 5 largest policy versions (seed 20261031).

    .venv/bin/python -I benchmarks/enterpriseops_gym/select_pilot.py
"""

import collections
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261031
BROKEN = {
    "task_20251212_172511_458_e6427839_47076c15",  # issue #21: last verifier query is broken
    "task_20251210_205620_593_391f1eff_ad65c160",  # issue #22: two verifiers cannot both pass
}

tasks = [t for t in json.loads((HERE / "tasks/itsm_oracle.json").read_text()) if t["task_id"] not in BROKEN]
by_version = collections.defaultdict(list)
for t in tasks:
    by_version[t["_policy_hash"]].append(t["task_id"])
rng = random.Random(SEED)
picked = []
for version, ids in sorted(by_version.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:5]:
    picked.append(
        {"task_id": rng.choice(sorted(ids)), "policy_version": version, "tasks_in_version": len(ids)}
    )
out = HERE / "tasks/pilot.json"
out.write_text(json.dumps({"seed": SEED, "rule": __doc__.split("\n\n")[0], "tasks": picked}, indent=2))
for p in picked:
    print(p)
